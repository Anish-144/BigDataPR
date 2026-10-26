"""Live health of every pipeline component, measured on request (never cached
fabrications). Each check reports status ``ok`` / ``degraded`` / ``down`` /
``unknown`` with the evidence it is based on."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from common.settings import get_settings
from generator.event_schema import DATA_TOPICS, Topic
from lakehouse.trino_client import run_query

LAKEHOUSE_TABLES = (
    "raw_agent_events", "agent_spans", "agent_run_metrics", "agent_evaluation_results", "agent_security_findings",
    "agent_anomaly_alerts", "agent_test_runs", "agent_registry", "stream_agent_metrics_1m", "dead_letter_events",
    "pipeline_batch_metrics", "worker_resource_metrics", "hourly_agent_summary", "daily_agent_summary",
)
SPARK_STATE_FILE = Path(os.environ.get("SPARK_STATE_FILE", "state/spark/stream_progress.json"))


def _timed(fn):
    t0 = time.perf_counter()
    try:
        out = fn()
        out.setdefault("status", "ok")
    except Exception as exc:  # report, never raise: health must degrade gracefully
        out = {"status": "down", "error": f"{type(exc).__name__}: {exc}"[:400]}
    out["check_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def kafka_watermarks() -> dict[str, dict[int, int]]:
    from confluent_kafka import Consumer, TopicPartition

    s = get_settings()
    c = Consumer({"bootstrap.servers": s.kafka_bootstrap, "group.id": "agentshield-health", "enable.auto.commit": False,
                  "socket.timeout.ms": 4000, "session.timeout.ms": 6000})
    try:
        md = c.list_topics(timeout=5)
        out: dict[str, dict[int, int]] = {}
        for t in [*(x.value for x in DATA_TOPICS), Topic.DLQ.value]:
            if t not in md.topics:
                continue
            out[t] = {}
            for p in md.topics[t].partitions:
                lo, hi = c.get_watermark_offsets(TopicPartition(t, p), timeout=5)
                out[t][p] = hi
        return out
    finally:
        c.close()


def check_kafka() -> dict[str, Any]:
    hw = kafka_watermarks()
    missing = [t.value for t in DATA_TOPICS if t.value not in hw]
    return {
        "status": "degraded" if missing else "ok",
        "topics": {t: {"partitions": len(p), "messages_total": sum(p.values())} for t, p in hw.items()},
        "missing_topics": missing,
        "_watermarks": hw,
    }


def read_spark_state() -> dict[str, Any] | None:
    if not SPARK_STATE_FILE.exists():
        return None
    return json.loads(SPARK_STATE_FILE.read_text())


def check_spark(watermarks: dict[str, dict[int, int]] | None) -> dict[str, Any]:
    state = read_spark_state()
    if state is None:
        return {"status": "unknown", "error": f"no progress file at {SPARK_STATE_FILE} (is spark-streaming running?)"}
    hb = datetime.fromisoformat(state["heartbeat"])
    age = (datetime.now(timezone.utc) - hb).total_seconds()
    queries = {}
    for name, q in state.get("queries", {}).items():
        progress = q.get("progress", [])
        last = progress[-1] if progress else {}
        lag_msgs = None
        if watermarks and last.get("sources"):
            lag_msgs = 0
            for src in last["sources"]:
                end = src.get("endOffset")
                end = json.loads(end) if isinstance(end, str) else (end or {})
                for topic, parts in end.items():
                    for p, off in parts.items():
                        lag_msgs += max(0, watermarks.get(topic, {}).get(int(p), off) - off)
        recent = [p for p in progress if p.get("numInputRows")]
        queries[name] = {
            "status": q.get("status"),
            "last_batch_id": last.get("batchId"),
            "last_progress_at": last.get("timestamp"),
            "last_input_rows": last.get("numInputRows"),
            "input_rows_per_sec": last.get("inputRowsPerSecond"),
            "processed_rows_per_sec": last.get("processedRowsPerSecond"),
            "last_trigger_ms": (last.get("durationMs") or {}).get("triggerExecution"),
            "consumer_lag_messages": lag_msgs,
            "watermark": (last.get("eventTime") or {}).get("watermark"),
            "rows_dropped_by_watermark": sum(
                (s.get("numRowsDroppedByWatermark") or 0) for p in progress for s in p.get("stateOperators", [])
            ),
            "recent_batches": [
                {"batch_id": p.get("batchId"), "rows": p.get("numInputRows"),
                 "trigger_ms": (p.get("durationMs") or {}).get("triggerExecution"), "at": p.get("timestamp")}
                for p in recent[-10:]
            ],
            "exception": q.get("exception"),
        }
    failed = any(q["status"] == "failed" for q in queries.values())
    status = "down" if failed or age > 120 else ("degraded" if age > 45 else "ok")
    return {"status": status, "heartbeat_age_s": round(age, 1), "started_at": state.get("started_at"), "queries": queries}


def check_trino() -> dict[str, Any]:
    t0 = time.perf_counter()
    run_query("SELECT 1")
    ping = (time.perf_counter() - t0) * 1000
    rows: dict[str, Any] = {}
    existing = {r[0] for r in run_query(
        "SELECT table_name FROM lakehouse.information_schema.tables WHERE table_schema = 'analytics'").rows}
    tables = [t for t in LAKEHOUSE_TABLES if t in existing]  # names come from the fixed tuple above, not user input
    if tables:
        # Iceberg "$files" metadata tables: counts/sizes without scanning data files.
        sql = " UNION ALL ".join(
            f"SELECT '{t}' AS t, coalesce(sum(record_count), 0) AS n, coalesce(sum(file_size_in_bytes), 0) AS b, "
            f"count(*) AS f FROM lakehouse.analytics.\"{t}$files\""
            for t in tables
        )
        res = run_query(sql)
        rows = {r[0]: {"rows": r[1], "bytes": r[2], "files": r[3]} for r in res.rows}
    rows.update({t: {"rows": None, "bytes": None, "files": None, "missing": True} for t in LAKEHOUSE_TABLES if t not in existing})
    recent = run_query(
        "SELECT count(*), avg(to_milliseconds(\"end\" - created)), approx_percentile(to_milliseconds(\"end\" - created), 0.95) "
        "FROM system.runtime.queries WHERE state = 'FINISHED' AND \"end\" IS NOT NULL AND created > now() - INTERVAL '15' MINUTE"
    )
    c, avg_ms, p95_ms = recent.rows[0]
    return {"ping_ms": round(ping, 1), "lakehouse_tables": rows,
            "recent_queries": {"window_minutes": 15, "finished": c, "avg_ms": avg_ms, "p95_ms": p95_ms}}


def check_postgres(engine) -> dict[str, Any]:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {}


def check_airflow() -> dict[str, Any]:
    url = get_settings().airflow_url.rstrip("/") + "/health"
    try:
        r = httpx.get(url, timeout=3)
    except httpx.HTTPError as exc:
        return {"status": "unknown", "error": f"Airflow not reachable ({exc.__class__.__name__}); optional profile 'orchestration'"}
    data = r.json()
    sched = (data.get("scheduler") or {}).get("status")
    return {"status": "ok" if sched == "healthy" else "degraded", "details": data}


def check_mongodb() -> dict[str, Any]:
    from backend.app.mongo import check_mongo_health
    return check_mongo_health()


def pipeline_health(engine) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_kafka = pool.submit(_timed, check_kafka)
        f_trino = pool.submit(_timed, check_trino)
        f_pg = pool.submit(_timed, lambda: check_postgres(engine))
        f_air = pool.submit(_timed, check_airflow)
        f_mongo = pool.submit(_timed, check_mongodb)
        kafka = f_kafka.result()
        components = {
            "kafka": kafka,
            "trino": f_trino.result(),
            "postgres": f_pg.result(),
            "airflow": f_air.result(),
            "mongodb": f_mongo.result(),
        }
    watermarks = kafka.pop("_watermarks", None)
    components["spark"] = _timed(lambda: check_spark(watermarks))
    core = ("kafka", "trino", "postgres", "spark")
    worst = max((components[c]["status"] for c in core), key=lambda s: ["ok", "unknown", "degraded", "down"].index(s))
    return {"status": worst, "checked_at": datetime.now(timezone.utc).isoformat(), "components": components}
