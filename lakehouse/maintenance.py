"""Lakehouse maintenance: data-quality gate, Iceberg compaction, snapshot expiry.

    python -m lakehouse.maintenance dq-check --max-quarantine-pct 1.0
    python -m lakehouse.maintenance compact --days 2
    python -m lakehouse.maintenance expire-snapshots --retention 7d

Compaction rewrites the small Parquet files produced by streaming micro-batch
commits (Trino `ALTER TABLE ... EXECUTE optimize`), limited to recent
partitions. File counts are measured before and after and reported.
Concurrent streaming commits are handled by Iceberg optimistic concurrency;
a conflicting maintenance commit fails and is retried by the scheduler.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

from lakehouse.sql_catalog import SQL_DIR, load_file
from lakehouse.trino_client import run_query

T = "lakehouse.analytics"
# streaming-written tables -> their partition date column
STREAMING_TABLES = {
    "raw_agent_events": "event_date", "agent_spans": "event_date", "agent_run_metrics": "event_date",
    "agent_evaluation_results": "event_date", "agent_security_findings": "event_date",
    "agent_anomaly_alerts": "event_date", "dead_letter_events": "ingest_date", "pipeline_batch_metrics": "event_date",
    "stream_agent_metrics_1m": "event_date", "worker_resource_metrics": "event_date",
}
RETENTION = re.compile(r"^\d{1,3}[dh]$")


def file_stats(table: str) -> tuple[int, int]:
    row = run_query(f'SELECT count(*), coalesce(sum(file_size_in_bytes), 0) FROM {T}."{table}$files"').rows[0]
    return int(row[0]), int(row[1])


def compact(days: int = 2, threshold_mb: int = 64) -> list[dict]:
    if not (0 < days <= 3650 and 0 < threshold_mb <= 1024):
        raise ValueError("days/threshold out of range")
    out = []
    for table, date_col in STREAMING_TABLES.items():
        before = file_stats(table)
        t0 = time.perf_counter()
        # Values are validated integers (not user text); Trino does not accept parameters in ALTER TABLE EXECUTE.
        run_query(f"ALTER TABLE {T}.{table} EXECUTE optimize(file_size_threshold => '{threshold_mb}MB') "
                  f"WHERE {date_col} >= current_date - INTERVAL '{days}' DAY")
        after = file_stats(table)
        out.append({"table": table, "files_before": before[0], "files_after": after[0], "bytes_before": before[1],
                    "bytes_after": after[1], "seconds": round(time.perf_counter() - t0, 2)})
    return out


def expire_snapshots(retention: str = "7d") -> list[dict]:
    if not RETENTION.match(retention):
        raise ValueError("retention must look like 7d or 168h")
    out = []
    for table in STREAMING_TABLES:
        n_before = run_query(f'SELECT count(*) FROM {T}."{table}$snapshots"').rows[0][0]
        run_query(f"ALTER TABLE {T}.{table} EXECUTE expire_snapshots(retention_threshold => '{retention}')")
        n_after = run_query(f'SELECT count(*) FROM {T}."{table}$snapshots"').rows[0][0]
        out.append({"table": table, "snapshots_before": n_before, "snapshots_after": n_after})
    return out


def dq_check(max_quarantine_pct: float = 1.0, days: int = 2) -> dict:
    """Fail (raise) when the share of quarantined records in the recent window exceeds the threshold."""
    st = next(s for s in load_file(SQL_DIR / "06_data_quality_checks.sql") if s.name == "dq_scorecard")
    sql, params = st.bind({"days": days})
    res = run_query(sql, params)
    checks = {r["check_name"]: r for r in res.as_dicts()}
    q = checks.get("quarantined_records", {})
    rate = q.get("issue_rate_pct") or 0.0
    report = {"days": days, "checks": checks, "quarantine_rate_pct": rate, "max_allowed_pct": max_quarantine_pct,
              "passed": rate <= max_quarantine_pct}
    if not report["passed"]:
        raise RuntimeError(f"data-quality gate failed: quarantine rate {rate}% > {max_quarantine_pct}%")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compact")
    c.add_argument("--days", type=int, default=2)
    c.add_argument("--threshold-mb", type=int, default=64)
    e = sub.add_parser("expire-snapshots")
    e.add_argument("--retention", default="7d")
    d = sub.add_parser("dq-check")
    d.add_argument("--max-quarantine-pct", type=float, default=1.0)
    d.add_argument("--days", type=int, default=2)
    a = ap.parse_args(argv)
    if a.cmd == "compact":
        out = compact(a.days, a.threshold_mb)
    elif a.cmd == "expire-snapshots":
        out = expire_snapshots(a.retention)
    else:
        out = dq_check(a.max_quarantine_pct, a.days)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
