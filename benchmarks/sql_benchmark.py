"""SQL performance experiment (spec section 9.3): measured, repeatable.

1. Three tiers answering the same question: raw JSON vs curated facts vs summary table.
2. Partition pruning: same aggregation with and without an event_date filter.
3. Table layout: point lookup by trace_id on the streaming-written table vs a
   trace_id-sorted copy (recreated here so it reflects current data).

Each query: 1 warm-up + N measured runs. Records client wall time, Trino
elapsed/cpu time, processed rows/bytes and physical input bytes, plus the
EXPLAIN ANALYZE text for the layout experiment. Writes
benchmarks/results/sql_benchmark_<timestamp>.json and .csv.

    python -m benchmarks.sql_benchmark --runs 5
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
from datetime import datetime, timezone

from common.settings import get_settings
from lakehouse.sql_catalog import SQL_DIR, load_file
from lakehouse.trino_client import run_query

T = "lakehouse.analytics"


def measure(name: str, sql: str, params: list | None, runs: int) -> dict:
    run_query(sql, params)  # warm-up (metadata caches, JIT)
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        res = run_query(sql, params)
        wall = (time.perf_counter() - t0) * 1000
        samples.append({"wall_ms": wall, **{k: res.stats.get(k) for k in (
            "elapsedTimeMillis", "cpuTimeMillis", "processedRows", "processedBytes", "physicalInputBytes", "totalSplits")}})
    walls = [s["wall_ms"] for s in samples]
    last = samples[-1]
    return {
        "query": name,
        "runs": runs,
        "wall_ms_median": round(statistics.median(walls), 1),
        "wall_ms_min": round(min(walls), 1),
        "wall_ms_max": round(max(walls), 1),
        "trino_elapsed_ms_median": statistics.median([s["elapsedTimeMillis"] or 0 for s in samples]),
        "cpu_ms_median": statistics.median([s["cpuTimeMillis"] or 0 for s in samples]),
        "processed_rows": last["processedRows"],
        "processed_bytes": last["processedBytes"],
        "physical_input_bytes": last["physicalInputBytes"],
        "splits": last["totalSplits"],
    }


def explain_input(sql: str, params: list | None) -> dict:
    """Run EXPLAIN ANALYZE and extract the table-scan input summary lines."""
    text = run_query("EXPLAIN ANALYZE " + sql, params).rows[0][0]
    inputs = re.findall(r"Input: ([\d,.]+\w* rows? \([^)]*\))", text)
    splits = re.findall(r"(\d+) splits?", text)
    return {"scan_inputs": inputs[:3], "plan_excerpt": "\n".join(l for l in text.splitlines() if "Input:" in l or "ScanFilter" in l or "TableScan" in l)[:2000],
            "splits_mentions": splits[:5]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()
    stmts = {s.name: s for s in load_file(SQL_DIR / "08_query_plan_experiments.sql") if s.name}

    data_size = run_query(f"""
        SELECT (SELECT count(*) FROM {T}.raw_agent_events), (SELECT count(*) FROM {T}.agent_run_metrics),
               (SELECT count(*) FROM {T}.agent_spans), (SELECT count(*) FROM {T}.daily_agent_summary)""").rows[0]
    results: dict = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dict(zip(["raw_agent_events", "agent_run_metrics", "agent_spans", "daily_agent_summary"], data_size)),
        "environment": "single-node Trino 467 in Docker (see docs/BENCHMARK_METHODOLOGY.md); NOT a multi-node cluster",
        "tiers": [], "pruning": [], "layout": {},
    }

    # 1) three-tier experiment
    for name in ("exp_tier_raw_json", "exp_tier_curated", "exp_tier_summary"):
        sql, params = stmts[name].bind({"days": args.days})
        r = measure(name, sql, params, args.runs)
        results["tiers"].append(r)
        print(f"{name:28s} median {r['wall_ms_median']:8.1f} ms  rows {r['processed_rows']}  bytes {r['physical_input_bytes']}")

    # 2) partition pruning (one day vs everything)
    base = f"SELECT agent_id, count(*), approx_percentile(latency_ms, 0.95) FROM {T}.agent_run_metrics"
    latest_day = run_query(f"SELECT max(event_date) FROM {T}.agent_run_metrics").rows[0][0]
    for label, sql, params in (
        ("with_partition_filter", base + " WHERE event_date = CAST(? AS date) GROUP BY agent_id", [latest_day]),
        ("without_partition_filter", base + " GROUP BY agent_id", None),
    ):
        r = measure(label, sql, params, args.runs)
        results["pruning"].append(r)
        print(f"{label:28s} median {r['wall_ms_median']:8.1f} ms  rows {r['processed_rows']}  bytes {r['physical_input_bytes']}")

    # 3) layout: unsorted (streaming-written) vs sorted vs sorted + small Parquet row groups
    from lakehouse.trino_client import connect

    variants = {
        "unsorted": ("agent_spans", None),
        "sorted": ("agent_spans_sorted_by_trace", {}),
        "sorted_small_rowgroups": ("agent_spans_sorted_small_rg", {"lakehouse.parquet_writer_block_size": "1MB"}),
    }
    layout: dict = {"variants": {}, "lookups": []}
    for label, (table, props) in variants.items():
        if props is None:
            continue
        conn = connect(session_properties=props)
        t0 = time.perf_counter()
        run_query(f"DROP TABLE IF EXISTS {T}.{table}", conn=conn)
        run_query(f"""CREATE TABLE {T}.{table}
                      WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date'], sorted_by = ARRAY['trace_id'])
                      AS SELECT * FROM {T}.agent_spans""", conn=conn)
        layout["variants"][label] = {"table": table, "session_properties": props,
                                     "build_ms": round((time.perf_counter() - t0) * 1000, 1)}
        conn.close()
    for label, (table, _) in variants.items():
        f = run_query(f'SELECT count(*), sum(file_size_in_bytes) FROM {T}."{table}$files"').rows[0]
        layout["variants"].setdefault(label, {"table": table})
        layout["variants"][label].update(data_files=f[0], bytes=f[1])
    traces = [r[0] for r in run_query(
        f"SELECT trace_id FROM {T}.agent_run_metrics ORDER BY xxhash64(to_utf8(run_id)) LIMIT 5").rows]
    for tid in traces:
        row = {"trace_id": tid}
        for label, (table, _) in variants.items():
            m = measure(f"lookup_{label}", f"SELECT span_id, span_kind, duration_ms FROM {T}.{table} WHERE trace_id = ?", [tid], args.runs)
            row[label] = {k: m[k] for k in ("wall_ms_median", "processed_rows", "physical_input_bytes", "splits")}
        layout["lookups"].append(row)
        print(f"lookup {tid[:8]}: rows read " + ", ".join(f"{l}={row[l]['processed_rows']}" for l in variants))
    for label, (table, _) in variants.items():
        layout[f"explain_{label}"] = explain_input(f"SELECT span_id FROM {T}.{table} WHERE trace_id = ?", [traces[0]])
    results["layout"] = layout

    out_dir = get_settings().results_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"sql_benchmark_{stamp}.json").write_text(json.dumps(results, indent=2, default=str))
    with open(out_dir / f"sql_benchmark_{stamp}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["experiment", "query", "wall_ms_median", "processed_rows", "physical_input_bytes", "splits"])
        for exp in ("tiers", "pruning"):
            for r in results[exp]:
                w.writerow([exp, r["query"], r["wall_ms_median"], r["processed_rows"], r["physical_input_bytes"], r["splits"]])
        for row in layout["lookups"]:
            for label in ("unsorted", "sorted", "sorted_small_rowgroups"):
                w.writerow(["layout", f"lookup_{label}:{row['trace_id']}", row[label]["wall_ms_median"],
                            row[label]["processed_rows"], row[label]["physical_input_bytes"], row[label]["splits"]])
    print(f"wrote {out_dir / f'sql_benchmark_{stamp}.json'}")


if __name__ == "__main__":
    main()
