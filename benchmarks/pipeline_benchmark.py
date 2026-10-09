"""End-to-end pipeline volume benchmark (spec section 9.2). Every number in the
output is measured during the run; nothing is estimated or extrapolated.

    python -m benchmarks.pipeline_benchmark --events 1000000 --workers 6

Steps:
 1. calibrate events/task for the scenario (in-process, null sink) -> task count
 2. produce to Kafka (generator workers), recording producer throughput
 3. poll until the lakehouse bronze table holds every produced record
 4. read Spark micro-batch metrics for the run window (throughput, lag)
 5. reconcile quarantined records against the injected dirty-record ground truth
 6. measure storage growth (Iceberg $files), post-load query latency, agent latency
 7. snapshot container resource usage (docker stats)
Writes benchmarks/results/pipeline_benchmark_<events>_<timestamp>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from common.settings import get_settings
from generator.producer import machine_info, run_test
from generator.runner import TestRunConfig, execute_task, make_context
from lakehouse.trino_client import run_query
from lakehouse.wait_for_ingest import kafka_total, lakehouse_total

T = "lakehouse.analytics"
TABLES = ("raw_agent_events", "agent_spans", "agent_run_metrics", "agent_evaluation_results",
          "agent_security_findings", "dead_letter_events", "stream_agent_metrics_1m")


def table_bytes() -> dict[str, dict]:
    sql = " UNION ALL ".join(
        f"SELECT '{t}', count(*), coalesce(sum(file_size_in_bytes), 0), coalesce(sum(record_count), 0) FROM {T}.\"{t}$files\""
        for t in TABLES)
    return {r[0]: {"files": r[1], "bytes": r[2], "rows": r[3]} for r in run_query(sql).rows}


def calibrate(cfg: TestRunConfig, n: int = 1500) -> float:
    ctx = make_context(cfg.model_copy(update={"tasks": n}), test_run_id="TR-00000000-calib0")
    total = sum(len(execute_task(ctx, i, "calib")) for i in range(n))
    return total / n


def docker_stats() -> list[dict]:
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], capture_output=True,
                             text=True, timeout=30, check=True).stdout
        return [{k: v for k, v in json.loads(line).items() if k in ("Name", "CPUPerc", "MemUsage", "MemPerc")}
                for line in out.splitlines() if line.strip()]
    except Exception as exc:
        return [{"error": f"docker stats unavailable: {exc}"}]


def docker_resources() -> dict:
    try:
        out = subprocess.run(["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True, timeout=30,
                             check=True).stdout
        info = json.loads(out)
        return {"cpus": info.get("NCPU"), "memory_gib": round(info.get("MemTotal", 0) / 2**30, 2),
                "server_version": info.get("ServerVersion"), "os": info.get("OperatingSystem")}
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=1_000_000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--scenario", default="generator/scenarios/benchmark.yaml")
    ap.add_argument("--timeout", type=float, default=3600)
    args = ap.parse_args()

    base_cfg = TestRunConfig.from_yaml(args.scenario, workers=args.workers)
    per_task = calibrate(base_cfg)
    tasks = math.ceil(args.events / per_task)
    cfg = base_cfg.model_copy(update={"tasks": tasks, "name": f"benchmark_{args.events}"})
    print(f"calibrated {per_task:.2f} events/task -> {tasks:,} tasks for ~{args.events:,} events", flush=True)

    kafka0, lake0, bytes0 = kafka_total(), lakehouse_total(), table_bytes()
    t0 = time.time()
    start_iso = datetime.now(timezone.utc).isoformat()
    summary = run_test(cfg, "kafka", get_settings().kafka_bootstrap, write_results=True)
    t_produced = time.time()
    produced = summary["events_emitted"]
    target = lake0 + produced
    print(f"produced {produced:,} events in {summary['wall_seconds']}s ({summary['events_per_sec']:,} ev/s)", flush=True)

    samples = []
    while True:
        n = lakehouse_total()
        samples.append({"t_s": round(time.time() - t0, 1), "lakehouse_rows_added": n - lake0})
        if n >= target:
            break
        if time.time() - t0 > args.timeout:
            raise SystemExit(f"timeout: lakehouse has {n - lake0:,} of {produced:,} records")
        time.sleep(5)
    t_done = time.time()
    resources = docker_stats()
    print(f"all {produced:,} records in the lakehouse after {t_done - t0:.1f}s", flush=True)

    tr = summary["test_run_id"]
    batches = run_query(f"""
        SELECT count(*), sum(input_rows), sum(invalid_rows), sum(duration_ms), min(batch_start), max(batch_end),
               avg(avg_ingest_lag_ms), approx_percentile(avg_ingest_lag_ms, 0.95), max(max_ingest_lag_ms),
               max(input_rows), approx_percentile(duration_ms, 0.95)
        FROM {T}.pipeline_batch_metrics
        WHERE query_name = 'lakehouse_fanout' AND input_rows > 0 AND batch_end >= from_iso8601_timestamp(?)""",
        [start_iso]).rows[0]
    first_start, last_end = batches[4], batches[5]
    span_s = (datetime.fromisoformat(last_end) - datetime.fromisoformat(first_start)).total_seconds()
    quarantine = run_query(f"""
        SELECT validation_error, count(*) FROM {T}.dead_letter_events
        WHERE raw_value LIKE ? GROUP BY 1""", [f"%{tr}%"]).rows
    agent = run_query(f"""
        SELECT count(*), avg(IF(task_success, 1e0, 0e0)), approx_percentile(latency_ms, 0.5),
               approx_percentile(latency_ms, 0.95), approx_percentile(latency_ms, 0.99)
        FROM {T}.agent_run_metrics WHERE test_run_id = ?""", [tr]).rows[0]
    bytes1 = table_bytes()

    def timed(sql: str, params=None, n: int = 3) -> float:
        out = []
        for _ in range(n):
            s = time.perf_counter()
            run_query(sql, params)
            out.append((time.perf_counter() - s) * 1000)
        return round(statistics.median(out), 1)

    q_latency = {
        "p95_by_version_full_table_ms": timed(f"SELECT agent_version, approx_percentile(latency_ms, 0.95) FROM {T}.agent_run_metrics GROUP BY 1"),
        "p95_by_version_this_run_ms": timed(f"SELECT agent_version, approx_percentile(latency_ms, 0.95) FROM {T}.agent_run_metrics WHERE test_run_id = ? GROUP BY 1", [tr]),
        "count_raw_events_ms": timed(f"SELECT count(*) FROM {T}.raw_agent_events"),
        "trace_lookup_ms": timed(f"SELECT * FROM {T}.agent_spans WHERE trace_id = (SELECT min(trace_id) FROM {T}.agent_run_metrics WHERE test_run_id = ?)", [tr]),
    }
    added = {t: {k: bytes1[t][k] - bytes0.get(t, {}).get(k, 0) for k in ("files", "bytes", "rows")} for t in TABLES}
    total_bytes = sum(v["bytes"] for v in added.values())
    injected_structural = {k: v for k, v in summary["dirty_injected"].items()
                           if k in ("malformed_json", "missing_event_id", "unknown_event_type", "bad_timestamp")}

    result = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "target_events": args.events,
        "test_run_id": tr,
        "environment": {"host": machine_info(), "docker": docker_resources(), "python": platform.python_version(),
                        "stack": "Kafka 3.9.0 (1 broker) | Spark 3.5.3 local[4] | Iceberg 1.7.1 | Trino 467 | MinIO (bitnamilegacy 2025.4.22)",
                        "note": "single machine, Docker Desktop; no multi-node scaling is claimed"},
        "workload": {"scenario": cfg.scenario_file, "seed": cfg.seed, "tasks": tasks, "workers": cfg.workers,
                     "calibrated_events_per_task": round(per_task, 3), "events_by_type": summary["events_by_type"],
                     "fault_profile": cfg.fault_profile, "dirty_rate": cfg.dirty_rate},
        "producer": {"events": produced, "wall_seconds": summary["wall_seconds"], "events_per_sec": summary["events_per_sec"],
                     "delivered": summary["delivery"]["delivered"], "failed": summary["delivery"]["failed"]},
        "end_to_end": {"seconds_produce_start_to_all_in_lakehouse": round(t_done - t0, 1),
                       "seconds_after_producer_finished": round(t_done - t_produced, 1),
                       "events_per_sec_end_to_end": round(produced / (t_done - t0), 1),
                       "ingest_curve": samples},
        "spark": {"batches": batches[0], "rows": batches[1], "invalid_rows": batches[2],
                  "busy_seconds": round((batches[3] or 0) / 1000, 1), "first_batch_start": first_start, "last_batch_end": last_end,
                  "rows_per_sec_over_span": round((batches[1] or 0) / span_s, 1) if span_s else None,
                  "rows_per_sec_while_busy": round((batches[1] or 0) / ((batches[3] or 1) / 1000), 1),
                  "largest_batch_rows": batches[9], "p95_batch_ms": batches[10],
                  "avg_ingest_lag_ms": batches[6], "p95_batch_avg_lag_ms": batches[7], "max_ingest_lag_ms": batches[8]},
        "validation": {"quarantined_by_reason": dict(quarantine), "injected_structural": injected_structural,
                       "quarantine_matches_injected": dict(quarantine) == {
                           ("invalid_event_time" if k == "bad_timestamp" else k): v for k, v in injected_structural.items()}},
        "storage": {"added_by_table": added, "added_mb_total": round(total_bytes / 2**20, 1),
                    "bytes_per_event": round(total_bytes / produced, 1)},
        "agent_latency_this_run": {"runs": agent[0], "success_rate": agent[1], "p50_ms": agent[2], "p95_ms": agent[3], "p99_ms": agent[4]},
        "query_latency_after_load": q_latency,
        "container_resources_at_completion": resources,
    }
    out_dir = get_settings().results_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = out_dir / f"pipeline_benchmark_{args.events}_{stamp}"
    base.with_suffix(".json").write_text(json.dumps(result, indent=2, default=str))
    base.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))
    print(f"wrote {base}.json/.md")


def render_markdown(r: dict) -> str:
    p, e, s, st, v = r["producer"], r["end_to_end"], r["spark"], r["storage"], r["validation"]
    a, q, env = r["agent_latency_this_run"], r["query_latency_after_load"], r["environment"]
    lines = [
        f"# Pipeline benchmark - {p['events']:,} events ({r['recorded_at'][:19]}Z)",
        "",
        f"Test run `{r['test_run_id']}`, scenario `{r['workload']['scenario']}`, seed {r['workload']['seed']}, "
        f"{r['workload']['tasks']:,} tasks, {r['workload']['workers']} producer workers.",
        f"Host: {env['host']['cpu_logical']} logical CPUs, {env['host']['ram_gb']} GB RAM; Docker: {env['docker'].get('cpus')} CPUs, "
        f"{env['docker'].get('memory_gib')} GiB. {env['stack']}. {env['note']}.",
        "",
        "| Measurement | Value |",
        "|---|---|",
        f"| Producer throughput | {p['events_per_sec']:,} events/s ({p['wall_seconds']} s, {p['failed']} delivery failures) |",
        f"| Produce start -> all records in lakehouse | {e['seconds_produce_start_to_all_in_lakehouse']} s "
        f"({e['events_per_sec_end_to_end']:,} events/s end-to-end) |",
        f"| Lakehouse catch-up after producer finished | {e['seconds_after_producer_finished']} s |",
        f"| Spark micro-batches | {s['batches']} (largest {s['largest_batch_rows']:,} rows, p95 duration {s['p95_batch_ms']:.0f} ms) |",
        f"| Spark throughput (rows / batch-span) | {s['rows_per_sec_over_span']:,} rows/s |",
        f"| Spark throughput while busy | {s['rows_per_sec_while_busy']:,} rows/s |",
        f"| Ingest lag (Kafka timestamp -> batch commit) | avg {s['avg_ingest_lag_ms']:.0f} ms, max {s['max_ingest_lag_ms']:.0f} ms |",
        f"| Quarantined records | {sum(v['quarantined_by_reason'].values()):,} (matches injected ground truth: {v['quarantine_matches_injected']}) |",
        f"| Storage added (Parquet/ZSTD on MinIO) | {st['added_mb_total']} MB ({st['bytes_per_event']} bytes/event across all tables) |",
        f"| Agent latency this run (simulated) | p50 {a['p50_ms']:.0f} ms, p95 {a['p95_ms']:.0f} ms, p99 {a['p99_ms']:.0f} ms; success {a['success_rate']:.4f} |",
        f"| Trino: p95 by version, full table | {q['p95_by_version_full_table_ms']} ms (median of 3) |",
        f"| Trino: p95 by version, this run | {q['p95_by_version_this_run_ms']} ms |",
        f"| Trino: trace lookup | {q['trace_lookup_ms']} ms |",
        "",
        "Container resources at completion:",
        "",
        "| Container | CPU | Memory |",
        "|---|---|---|",
    ]
    for c in r["container_resources_at_completion"]:
        if "Name" in c:
            lines.append(f"| {c['Name']} | {c['CPUPerc']} | {c['MemUsage']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
