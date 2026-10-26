"""AgentShield Spark Structured Streaming job: Kafka -> Iceberg (MinIO).

Two streaming queries share one SparkSession:

1. ``lakehouse_fanout`` (foreachBatch, processing-time trigger)
   * parses the contract envelope, validates structure (malformed JSON,
     missing IDs, unknown types, unparseable timestamps, topic mismatch,
     missing required context/payload fields),
   * writes EVERY record to ``raw_agent_events`` (bronze) with is_valid /
     validation_error, and invalid records to ``dead_letter_events``,
   * fans valid records out to the curated (silver) fact tables with derived
     features and row-level data-quality flags,
   * upserts ``agent_test_runs`` with an Iceberg MERGE,
   * appends one row per micro-batch to ``pipeline_batch_metrics``.
2. ``window_metrics_1m`` - event-time tumbling windows with a watermark,
   appended to ``stream_agent_metrics_1m``.

Delivery semantics: Kafka offsets are tracked in the checkpoint. A batch that
failed mid-way is re-executed after restart; each Iceberg commit carries
``agentshield.query``/``agentshield.batch_id`` snapshot properties so the
re-executed batch skips tables it had already committed (effectively-once per
table). See docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQueryListener
from pyspark.sql.window import Window

from streaming import feature_engineering as fe
from streaming.schemas import (
    ENVELOPE_DDL,
    EVENT_PAYLOAD,
    EVENT_TOPIC,
    PAYLOAD_DDL,
    REQUIRED_CONTEXT,
    REQUIRED_PAYLOAD,
    SUPPORTED_SCHEMA_VERSIONS,
    TIMESTAMP_FIELDS,
)
from streaming.window_aggregations import run_metrics_stream, windowed_metrics

NS = "lakehouse.analytics"
PAYLOAD_COL = {key: "p_" + key.replace(".", "_") for key in PAYLOAD_DDL}
TOPICS = ["agent-traces", "agent-metrics", "agent-evaluations", "agent-security-events", "agent-alerts"]


def env(name: str, default: str) -> str:
    return os.environ.get(name) or default


CHECKPOINT_DIR = env("CHECKPOINT_DIR", "/opt/agentshield/checkpoints")
STATE_DIR = Path(env("STATE_DIR", "/opt/agentshield/state"))
TRIGGER = f"{env('TRIGGER_SECONDS', '10')} seconds"
MAX_OFFSETS = env("MAX_OFFSETS_PER_TRIGGER", "300000")
WATERMARK = env("WATERMARK_DELAY", "30 minutes")
WINDOW = env("WINDOW_DURATION", "1 minute")


def build_spark() -> SparkSession:
    s3 = env("S3_ENDPOINT", "http://minio:9000")
    builder = (
        SparkSession.builder.appName("agentshield-streaming")
        .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .config("spark.sql.catalog.lakehouse", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.lakehouse.type", "jdbc")
        .config("spark.sql.catalog.lakehouse.uri", env("ICEBERG_JDBC_URI", "jdbc:postgresql://postgres:5432/iceberg_catalog"))
        .config("spark.sql.catalog.lakehouse.jdbc.user", env("ICEBERG_JDBC_USER", "iceberg"))
        .config("spark.sql.catalog.lakehouse.jdbc.password", env("ICEBERG_JDBC_PASSWORD", "iceberg"))
        .config("spark.sql.catalog.lakehouse.jdbc.schema-version", "V1")
        .config("spark.sql.catalog.lakehouse.warehouse", env("WAREHOUSE", "s3://warehouse/"))
        .config("spark.sql.catalog.lakehouse.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
        .config("spark.sql.catalog.lakehouse.s3.endpoint", s3)
        .config("spark.sql.catalog.lakehouse.s3.path-style-access", "true")
        .config("spark.sql.catalog.lakehouse.s3.access-key-id", env("AWS_ACCESS_KEY_ID", "agentshield"))
        .config("spark.sql.catalog.lakehouse.s3.secret-access-key", env("AWS_SECRET_ACCESS_KEY", "agentshield123"))
        .config("spark.sql.catalog.lakehouse.client.region", env("AWS_REGION", "us-east-1"))
        .config("spark.sql.catalog.lakehouse.cache-enabled", "false")
        .config("spark.sql.defaultCatalog", "lakehouse")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", env("SHUFFLE_PARTITIONS", "8"))
        .config("spark.sql.streaming.stateStore.providerClass",
                "org.apache.spark.sql.execution.streaming.state.HDFSBackedStateStoreProvider")
        .config("spark.sql.adaptive.enabled", "true")
    )
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel(env("SPARK_LOG_LEVEL", "WARN"))
    return spark


# --------------------------------------------------------------------------- progress listener


class ProgressFileListener(StreamingQueryListener):
    """Persists recent StreamingQueryProgress (incl. Kafka offsets-behind-latest) for the API."""

    def __init__(self, path: Path, keep: int = 30):
        self.path, self.keep = path, keep
        self.lock = threading.Lock()
        self.state: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "queries": {}}
        path.parent.mkdir(parents=True, exist_ok=True)
        self._flush()

    def _flush(self) -> None:
        self.state["heartbeat"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, default=str))
        os.replace(tmp, self.path)

    def _q(self, name: str) -> dict:
        return self.state["queries"].setdefault(name or "unnamed", {"status": "starting", "progress": []})

    def onQueryStarted(self, event) -> None:
        with self.lock:
            q = self._q(event.name)
            q.update(status="running", id=str(event.id), run_id=str(event.runId), started=str(event.timestamp))
            self._flush()

    def onQueryProgress(self, event) -> None:
        p = json.loads(event.progress.json)
        compact = {
            "batchId": p.get("batchId"),
            "timestamp": p.get("timestamp"),
            "numInputRows": p.get("numInputRows"),
            "inputRowsPerSecond": p.get("inputRowsPerSecond"),
            "processedRowsPerSecond": p.get("processedRowsPerSecond"),
            "durationMs": p.get("durationMs"),
            "eventTime": p.get("eventTime"),
            "stateOperators": [
                {k: s.get(k) for k in ("numRowsTotal", "numRowsUpdated", "numRowsDroppedByWatermark", "memoryUsedBytes")}
                for s in p.get("stateOperators", [])
            ],
            "sources": [
                {"description": s.get("description"), "metrics": s.get("metrics"), "endOffset": s.get("endOffset"),
                 "latestOffset": s.get("latestOffset")}
                for s in p.get("sources", [])
            ],
        }
        with self.lock:
            q = self._q(p.get("name"))
            q["status"] = "running"
            q["progress"] = (q["progress"] + [compact])[-self.keep:]
            self._flush()

    def onQueryIdle(self, event) -> None:  # Spark >= 3.5
        with self.lock:
            self._flush()

    def onQueryTerminated(self, event) -> None:
        with self.lock:
            for q in self.state["queries"].values():
                if q.get("id") == str(event.id):
                    q["status"] = "failed" if event.exception else "terminated"
                    q["exception"] = (event.exception or "")[:2000]
            self._flush()


# --------------------------------------------------------------------------- helpers


class TableWriter:
    """Appends DataFrames aligned to the current Iceberg table schema, tagging snapshots with batch ids."""

    def __init__(self, spark: SparkSession, query_name: str):
        self.spark, self.query_name = spark, query_name
        self.first_batch = True

    def align(self, df: DataFrame, table: str) -> DataFrame:
        target = self.spark.table(f"{NS}.{table}").schema  # cache disabled -> always current (schema evolution)
        cols = df.columns
        return df.select(
            *[
                (F.col(f.name) if f.name in cols else F.lit(None)).cast(f.dataType).alias(f.name)
                for f in target.fields
            ]
        )

    def already_committed(self, table: str, batch_id: int) -> bool:
        rows = self.spark.sql(
            f"SELECT summary FROM {NS}.{table}.snapshots ORDER BY committed_at DESC LIMIT 50"
        ).collect()
        for r in rows:
            s = r["summary"] or {}
            if s.get("agentshield.query") == self.query_name and s.get("agentshield.batch_id") == str(batch_id):
                return True
        return False

    def append(self, df: DataFrame, table: str, batch_id: int) -> None:
        if self.first_batch and self.already_committed(table, batch_id):
            print(f"[{self.query_name}] batch {batch_id}: {table} already committed, skipping (replay)", flush=True)
            return
        (
            self.align(df, table)
            .writeTo(f"{NS}.{table}")
            .option("snapshot-property.agentshield.query", self.query_name)
            .option("snapshot-property.agentshield.batch_id", str(batch_id))
            .append()
        )


def parse_and_validate(batch: DataFrame, ingested_at: datetime) -> DataFrame:
    """Envelope parsing + structural validation. Adds is_valid / validation_error."""
    known_types = list(EVENT_TOPIC.keys())
    df = batch.select(
        F.col("topic").alias("kafka_topic"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_timestamp"),
        F.col("value").cast("string").alias("raw_value"),
    ).withColumn(
        # The corrupt-record column flags any document that is not valid JSON as a whole. Without it,
        # PERMISSIVE parsing returns *partial* results (e.g. a record truncated inside "payload" kept its
        # envelope fields) and was mislabelled missing_payload instead of malformed_json.
        "e", F.from_json("raw_value", ENVELOPE_DDL + ", _corrupt_record STRING",
                         {"columnNameOfCorruptRecord": "_corrupt_record"}),
    )
    df = df.withColumn("ingested_at", F.lit(ingested_at).cast("timestamp")).withColumn(
        "event_time_ts", fe.ts(F.col("e.event_time"))
    )

    topic_expected = F.create_map(*[x for kv in EVENT_TOPIC.items() for x in (F.lit(kv[0]), F.lit(kv[1]))])
    missing_ctx = F.lit(None).cast("string")
    for etype, fields in REQUIRED_CONTEXT.items():
        if fields:
            cond = F.lit(False)
            for f in fields:
                cond = cond | F.col(f"e.{f}").isNull()
            missing_ctx = F.when((F.col("e.event_type") == etype) & cond, F.lit("missing_required_context")).otherwise(missing_ctx)

    # Parse each payload type exactly once (only for rows of that type); the
    # parsed struct columns are reused by validation and by the fan-out writes.
    for key, ddl in PAYLOAD_DDL.items():
        types = [t for t, k in EVENT_PAYLOAD.items() if k == key]
        df = df.withColumn(PAYLOAD_COL[key], F.when(F.col("e.event_type").isin(types), F.from_json(F.col("e.payload"), ddl)))

    payload_err = F.lit(None).cast("string")
    for etype, key in EVENT_PAYLOAD.items():
        parsed = F.col(PAYLOAD_COL[key])
        bad = parsed.isNull()
        for f in REQUIRED_PAYLOAD[key]:
            bad = bad | parsed.getField(f).isNull()
        bad_ts = F.lit(False)
        for f in TIMESTAMP_FIELDS[key]:
            bad_ts = bad_ts | (parsed.getField(f).isNotNull() & fe.ts(parsed.getField(f)).isNull())
        payload_err = F.when(
            F.col("e.event_type") == etype,
            F.when(bad, F.lit("invalid_payload")).when(bad_ts, F.lit("invalid_payload_timestamp")).otherwise(payload_err),
        ).otherwise(payload_err)

    error = (
        F.when(F.col("e").isNull() | F.col("e._corrupt_record").isNotNull()
               | (F.col("e.event_type").isNull() & F.col("e.event_id").isNull()), "malformed_json")
        .when(F.col("e.event_id").isNull(), "missing_event_id")
        .when(~F.col("e.event_type").isin(known_types), "unknown_event_type")
        .when(F.col("e.event_time").isNull() | F.col("event_time_ts").isNull(), "invalid_event_time")
        .when(~F.col("e.schema_version").isin(list(SUPPORTED_SCHEMA_VERSIONS)), "unsupported_schema_version")
        .when(topic_expected[F.col("e.event_type")] != F.col("kafka_topic"), "topic_mismatch")
        .when(F.col("e.payload").isNull(), "missing_payload")
        .when(missing_ctx.isNotNull(), missing_ctx)
        .otherwise(payload_err)
    )
    return (
        df.withColumn("validation_error", error)
        .withColumn("is_valid", F.col("validation_error").isNull())
        .withColumn("event_date", F.coalesce(F.to_date("event_time_ts"), F.to_date("ingested_at")))
    )


def envelope_cols() -> list:
    return [
        F.col("e.event_id").alias("event_id"),
        F.col("e.test_run_id").alias("test_run_id"),
        F.col("e.run_id").alias("run_id"),
        F.col("e.trace_id").alias("trace_id"),
        F.col("e.agent_id").alias("agent_id"),
        F.col("e.agent_version").alias("agent_version"),
        F.col("e.scenario_id").alias("scenario_id"),
        F.col("event_time_ts").alias("event_time"),
        "event_date",
        "ingested_at",
    ]


def payload(df: DataFrame, key: str) -> DataFrame:
    return df.withColumn("p", F.col(PAYLOAD_COL[key]))


# --------------------------------------------------------------------------- fan-out batch


def make_fanout(spark: SparkSession):
    writer = TableWriter(spark, "lakehouse_fanout")

    def process(batch: DataFrame, batch_id: int) -> None:
        t0 = time.time()
        batch_start = datetime.now(timezone.utc)
        df = parse_and_validate(batch, batch_start).withColumn("batch_id", F.lit(batch_id).cast("long")).persist()
        counts = {
            (r["event_type"], r["is_valid"]): r["n"]
            for r in df.groupBy(F.col("e.event_type").alias("event_type"), "is_valid").agg(F.count(F.lit(1)).alias("n")).collect()
        }
        total = sum(counts.values())
        if total == 0:
            df.unpersist()
            writer.first_batch = False
            return
        written: dict[str, int] = {}
        n_valid = sum(n for (t, ok), n in counts.items() if ok)
        n_invalid = total - n_valid

        # Bronze: everything, valid or not.
        raw = df.select(
            F.col("e.event_id").alias("event_id"), F.col("e.event_type").alias("event_type"),
            F.col("e.schema_version").alias("schema_version"), F.col("event_time_ts").alias("event_time"),
            "event_date", F.col("e.test_run_id").alias("test_run_id"), F.col("e.run_id").alias("run_id"),
            F.col("e.trace_id").alias("trace_id"), F.col("e.agent_id").alias("agent_id"),
            F.col("e.agent_version").alias("agent_version"), F.col("e.scenario_id").alias("scenario_id"),
            F.col("e.producer").alias("producer"), "kafka_topic", "kafka_partition", "kafka_offset",
            "kafka_timestamp", "ingested_at", "batch_id", "is_valid", "validation_error", "raw_value",
        )
        writer.append(raw, "raw_agent_events", batch_id)
        written["raw_agent_events"] = total

        if n_invalid:
            dlq = df.where(~F.col("is_valid")).select(
                "kafka_topic", "kafka_partition", "kafka_offset", "kafka_timestamp",
                F.col("e.event_id").alias("event_id"), F.col("e.event_type").alias("event_type"),
                "validation_error", "raw_value", "ingested_at", F.to_date("ingested_at").alias("ingest_date"), "batch_id",
            )
            writer.append(dlq, "dead_letter_events", batch_id)
            written["dead_letter_events"] = n_invalid

        valid = df.where(F.col("is_valid"))

        def n(t: str) -> int:
            return counts.get((t, True), 0)

        if n("span.completed"):
            p = payload(valid.where(F.col("e.event_type") == "span.completed"), "span.completed")
            spans = p.select(
                *envelope_cols(), "batch_id",
                *[F.col(f"p.{c}").alias(c) for c in (
                    "span_id", "parent_span_id", "span_kind", "span_name", "duration_ms", "status", "error_category",
                    "step_index", "attempt", "model_name", "input_tokens", "output_tokens", "ttft_ms", "tool_name",
                    "tool_args_valid", "tool_allowed", "policy_decision", "data_classification", "retrieved_doc_ids",
                    "retrieval_scores", "top_k", "delegated_agent_id", "attributes")],
                fe.ts("p.start_time").alias("start_time"), fe.ts("p.end_time").alias("end_time"),
            )
            writer.append(fe.span_features(spans), "agent_spans", batch_id)
            written["agent_spans"] = n("span.completed")

        if n("run.metrics"):
            p = payload(valid.where(F.col("e.event_type") == "run.metrics"), "run.metrics")
            runs = p.select(
                *envelope_cols(), "batch_id",
                *[F.col(f"p.{c}").alias(c) for c in (
                    "agent_name", "agent_release_seq", "model_name", "prompt_version", "workload_type", "difficulty",
                    "task_id", "status", "task_success", "latency_ms", "ttft_ms", "input_tokens", "output_tokens",
                    "llm_calls", "tool_calls", "tool_errors", "tool_timeouts", "retries", "span_count", "max_depth",
                    "distinct_tools", "max_consecutive_same_tool", "avg_tool_latency_ms", "retrieval_count",
                    "policy_denials", "error_category", "estimated_cost_usd", "cost_source", "injected_faults",
                    "worker_id", "routing_strategy")],
                fe.ts("p.start_time").alias("start_time"), fe.ts("p.end_time").alias("end_time"),
            )
            writer.append(fe.run_features(runs), "agent_run_metrics", batch_id)
            written["agent_run_metrics"] = n("run.metrics")

        if n("evaluation.result"):
            p = payload(valid.where(F.col("e.event_type") == "evaluation.result"), "evaluation.result")
            evals = p.select(*envelope_cols(), "batch_id", "p.*")
            writer.append(evals, "agent_evaluation_results", batch_id)
            written["agent_evaluation_results"] = n("evaluation.result")

        if n("security.finding"):
            p = payload(valid.where(F.col("e.event_type") == "security.finding"), "security.finding")
            writer.append(p.select(*envelope_cols(), "batch_id", "p.*"), "agent_security_findings", batch_id)
            written["agent_security_findings"] = n("security.finding")

        if n("anomaly.alert"):
            p = payload(valid.where(F.col("e.event_type") == "anomaly.alert"), "anomaly.alert")
            alerts = p.select(
                *envelope_cols(), "batch_id",
                *[F.col(f"p.{c}").alias(c) for c in (
                    "alert_id", "detector", "detector_version", "anomaly_type", "severity", "score", "agent_name",
                    "related_run_ids", "related_trace_ids", "supporting_metrics", "explanation")],
                fe.ts("p.window_start").alias("window_start"), fe.ts("p.window_end").alias("window_end"),
            )
            writer.append(alerts, "agent_anomaly_alerts", batch_id)
            written["agent_anomaly_alerts"] = n("anomaly.alert")

        if n("worker.resource"):
            p = payload(valid.where(F.col("e.event_type") == "worker.resource"), "worker.resource")
            writer.append(p.select(*envelope_cols(), "batch_id", "p.*"), "worker_resource_metrics", batch_id)
            written["worker_resource_metrics"] = n("worker.resource")

        tr_n = n("test_run.started") + n("test_run.completed")
        if tr_n:
            p = payload(valid.where(F.col("e.event_type").isin("test_run.started", "test_run.completed")), "test_run")
            latest = Window.partitionBy("test_run_id").orderBy(F.col("last_event_time").desc(), F.col("kafka_offset").desc())
            tr = (
                p.select(
                    F.col("e.test_run_id").alias("test_run_id"), "p.test_run_name", "p.status", "p.seed",
                    "p.requested_tasks", F.col("p.workers").cast("int").alias("workers"), "p.time_mode",
                    "p.scenario_file", "p.workload_mix", "p.fault_profile",
                    fe.ts("p.started_at").alias("started_at"), fe.ts("p.ended_at").alias("ended_at"),
                    fe.ts("p.sim_window_start").alias("sim_window_start"), fe.ts("p.sim_window_end").alias("sim_window_end"),
                    "p.total_runs", "p.total_events", "p.triggered_by", "p.notes",
                    F.col("event_time_ts").alias("last_event_time"), F.col("ingested_at").alias("updated_at"), "kafka_offset",
                )
                .withColumn("rn", F.row_number().over(latest))
                .where("rn = 1")
                .drop("rn", "kafka_offset")
            )
            writer.align(tr, "agent_test_runs").createOrReplaceTempView("test_run_updates")
            batch.sparkSession.sql(f"""
                MERGE INTO {NS}.agent_test_runs t
                USING test_run_updates s
                ON t.test_run_id = s.test_run_id
                WHEN MATCHED AND s.last_event_time >= t.last_event_time THEN UPDATE SET *
                WHEN NOT MATCHED THEN INSERT *
            """)
            written["agent_test_runs"] = tr_n

        batch_end = datetime.now(timezone.utc)
        lag = df.agg(
            F.min("kafka_timestamp").alias("min_ts"), F.max("kafka_timestamp").alias("max_ts"),
            F.avg((F.lit(batch_end).cast("timestamp").cast("double") - F.col("kafka_timestamp").cast("double")) * 1000).alias("avg_lag"),
            F.max((F.lit(batch_end).cast("timestamp").cast("double") - F.col("kafka_timestamp").cast("double")) * 1000).alias("max_lag"),
        ).collect()[0]
        metrics = spark.createDataFrame(
            [("lakehouse_fanout", batch_id, batch_start, batch_end, (time.time() - t0) * 1000.0, total, n_valid,
              n_invalid, written, lag["min_ts"], lag["max_ts"], lag["avg_lag"], lag["max_lag"], batch_end.date())],
            "query_name string, batch_id long, batch_start timestamp, batch_end timestamp, duration_ms double, "
            "input_rows long, valid_rows long, invalid_rows long, rows_written map<string,long>, min_kafka_ts timestamp, "
            "max_kafka_ts timestamp, avg_ingest_lag_ms double, max_ingest_lag_ms double, event_date date",
        )
        writer.append(metrics, "pipeline_batch_metrics", batch_id)
        df.unpersist()
        writer.first_batch = False
        print(f"[lakehouse_fanout] batch {batch_id}: {total} rows ({n_invalid} invalid) in {time.time() - t0:.1f}s "
              f"-> {written}", flush=True)

    return process


def make_window_sink(spark: SparkSession):
    writer = TableWriter(spark, "window_metrics_1m")

    def process(batch: DataFrame, batch_id: int) -> None:
        out = batch.withColumn("emitted_at", F.current_timestamp()).withColumn("batch_id", F.lit(batch_id).cast("long"))
        if out.isEmpty():
            writer.first_batch = False
            return
        writer.append(out, "stream_agent_metrics_1m", batch_id)
        writer.first_batch = False

    return process


def kafka_source(spark: SparkSession, topics: list[str]) -> DataFrame:
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", env("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"))
        .option("subscribe", ",".join(topics))
        .option("startingOffsets", env("STARTING_OFFSETS", "earliest"))
        .option("maxOffsetsPerTrigger", MAX_OFFSETS)
        .option("failOnDataLoss", "false")
        .load()
    )


def wait_for_tables(spark: SparkSession, timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    while True:
        try:
            spark.table(f"{NS}.raw_agent_events").schema
            spark.table(f"{NS}.stream_agent_metrics_1m").schema
            return
        except Exception as exc:
            if time.time() > deadline:
                raise RuntimeError("lakehouse tables not found - did lakehouse-init run?") from exc
            print("waiting for lakehouse tables ...", flush=True)
            time.sleep(5)


def main() -> None:
    spark = build_spark()
    wait_for_tables(spark)
    listener = ProgressFileListener(STATE_DIR / "stream_progress.json")
    spark.streams.addListener(listener)

    fanout = (
        kafka_source(spark, TOPICS)
        .writeStream.queryName("lakehouse_fanout")
        .foreachBatch(make_fanout(spark))
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/lakehouse_fanout")
        .trigger(processingTime=TRIGGER)
        .start()
    )
    windows = (
        windowed_metrics(run_metrics_stream(kafka_source(spark, ["agent-metrics"])), WINDOW, WATERMARK)
        .writeStream.queryName("window_metrics_1m")
        .outputMode("append")
        .foreachBatch(make_window_sink(spark))
        .option("checkpointLocation", f"{CHECKPOINT_DIR}/window_metrics_1m")
        .trigger(processingTime=TRIGGER)
        .start()
    )
    print(f"started queries: {fanout.name}, {windows.name} (trigger={TRIGGER}, watermark={WATERMARK})", flush=True)

    def heartbeat() -> None:
        while True:
            time.sleep(15)
            with listener.lock:
                listener._flush()

    threading.Thread(target=heartbeat, daemon=True).start()
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
