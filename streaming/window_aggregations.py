"""Event-time windowed aggregation (Spark Structured Streaming, stateful).

1-minute tumbling windows per agent version over ``run.metrics`` events. A
watermark bounds state: a window is emitted once (append mode) after the
watermark passes its end, and events arriving later than the watermark are
dropped from this aggregate (they are still stored in the raw and curated
tables; the drop count is reported in streaming progress as
``numRowsDroppedByWatermark``).
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from streaming.schemas import ENVELOPE_DDL, PAYLOAD_DDL


def run_metrics_stream(kafka_df: DataFrame) -> DataFrame:
    env = kafka_df.select(F.from_json(F.col("value").cast("string"), ENVELOPE_DDL).alias("e"))
    runs = env.where(F.col("e.event_type") == "run.metrics").select(
        F.col("e.event_time").cast("timestamp").alias("event_time"),
        F.col("e.agent_id").alias("agent_id"),
        F.col("e.agent_version").alias("agent_version"),
        F.from_json(F.col("e.payload"), PAYLOAD_DDL["run.metrics"]).alias("p"),
    )
    return runs.where(F.col("event_time").isNotNull() & F.col("agent_id").isNotNull() & F.col("p.latency_ms").isNotNull())


def windowed_metrics(runs: DataFrame, window: str, watermark: str) -> DataFrame:
    return (
        runs.withWatermark("event_time", watermark)
        .groupBy(F.window("event_time", window), "agent_id", "agent_version")
        .agg(
            F.count(F.lit(1)).alias("runs"),
            F.sum(F.when(F.col("p.task_success"), 1).otherwise(0)).alias("successes"),
            F.sum(F.when(F.col("p.status") == "failed", 1).otherwise(0)).alias("failures"),
            F.sum(F.when(F.col("p.status") == "timeout", 1).otherwise(0)).alias("timeouts"),
            F.sum("p.latency_ms").alias("sum_latency_ms"),
            F.max("p.latency_ms").alias("max_latency_ms"),
            F.percentile_approx("p.latency_ms", 0.95, 1000).alias("approx_p95_latency_ms"),
            F.sum(F.col("p.input_tokens") + F.col("p.output_tokens")).alias("total_tokens"),
            F.sum("p.tool_calls").alias("tool_calls"),
            F.sum("p.tool_errors").alias("tool_errors"),
            F.sum("p.retries").alias("retries"),
            F.sum("p.policy_denials").alias("policy_denials"),
        )
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            F.to_date(F.col("window.start")).alias("event_date"),
            "agent_id", "agent_version", "runs", "successes", "failures", "timeouts", "sum_latency_ms",
            "max_latency_ms", "approx_p95_latency_ms", "total_tokens", "tool_calls", "tool_errors", "retries",
            "policy_denials",
        )
    )
