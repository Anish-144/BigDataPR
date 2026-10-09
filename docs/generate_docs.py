"""Generate the data-driven documentation from the live system and measured results.

    python -m docs.generate_docs            # all
    python -m docs.generate_docs dictionary showcase api benchmarks

* DATA_DICTIONARY.md  - from lakehouse.information_schema (live column types) + descriptions below
* SQL_SHOWCASE.md     - from sql/*.sql annotations + docs/sql_outputs/<query>.json (real exported results)
* API.md              - from the running API's OpenAPI document
* BENCHMARK_REPORT.md - from benchmarks/results/*.json (measured values only; nothing typed by hand)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common.settings import REPO_ROOT

DOCS = REPO_ROOT / "docs"
RESULTS = REPO_ROOT / "benchmarks" / "results"
OUTPUTS = DOCS / "sql_outputs"

TABLE_DOCS = {
    "raw_agent_events": "Bronze. Every Kafka record exactly as received (valid or not) with Kafka coordinates and validation result.",
    "dead_letter_events": "Structurally invalid records quarantined by Spark, with the rejection reason and raw bytes.",
    "agent_spans": "Fact. One row per span (OpenTelemetry-style): model calls, retrievals, tool calls, policy checks, delegation.",
    "agent_run_metrics": "Fact. One row per agent run (task execution) with outcome, latency, tokens, tools, cost estimate and labels.",
    "agent_evaluation_results": "Fact. One row per run x evaluation metric (long format). Deterministic and model-judged scores are separated by evaluator_type.",
    "agent_security_findings": "Fact. Policy/content-detector findings linked to trace, span and policy rule.",
    "agent_anomaly_alerts": "Fact. Alerts from rule detectors and the Isolation Forest (published via Kafka topic agent-alerts).",
    "worker_resource_metrics": "Fact. CPU/memory samples of the load-generator worker processes.",
    "stream_agent_metrics_1m": "Spark event-time 1-minute windows per agent version (watermark-finalised, append mode).",
    "pipeline_batch_metrics": "One row per Spark micro-batch: rows in/valid/invalid, duration, ingest lag.",
    "agent_test_runs": "Dimension. One row per test run, upserted with MERGE from lifecycle events.",
    "agent_registry": "Dimension. Agent versions with release order, model, prompt version and policy limits (from config).",
    "dim_model_pricing": "Dimension. ILLUSTRATIVE local prices for mock models (source of every cost estimate).",
    "dim_policy_rules": "Dimension. Security policy rules (policy-as-code, config/policies.yaml).",
    "dim_scenarios": "Dimension. Test scenarios (generator/scenarios/*.yaml).",
    "dim_date": "Dimension. Calendar.",
    "hourly_agent_summary": "Summary. Hourly per-version aggregates incl. a serialized T-Digest of latency (sql/07).",
    "daily_agent_summary": "Summary. Daily per-version aggregates rolled up from hourly (percentiles from merged T-Digests).",
    "agent_regression_results": "Regression-gate results: one row per gate run x check.",
    "agent_spans_sorted_by_trace": "Experiment copy of agent_spans sorted by trace_id (sql/08 layout experiment).",
    "agent_spans_sorted_small_rg": "Experiment copy sorted by trace_id with 1 MB Parquet row groups (sql/08 layout experiment).",
    "demo_evolution": "Scratch table for the schema-evolution / rollback demo (sql/09).",
}
COLUMN_DOCS = {
    "event_id": "Unique event id (UUID, deterministic per seed).",
    "event_type": "Contract event type (span.completed, run.metrics, evaluation.result, security.finding, anomaly.alert, test_run.*, worker.resource).",
    "schema_version": "Event contract version (1.0, 1.1).",
    "event_time": "Event time (UTC). Simulated for historical scenarios, wall-clock for realtime runs.",
    "event_date": "UTC date of event_time; partition column.",
    "ingest_date": "UTC date of ingestion; partition column for dead letters.",
    "test_run_id": "Benchmark/test run id, TR-YYYYMMDD-xxxxxx.",
    "run_id": "Agent run (one task execution) id, R-<test-run>-<seq>.",
    "trace_id": "OpenTelemetry-style 32-hex trace id; 1:1 with run_id.",
    "span_id": "16-hex span id.", "parent_span_id": "Parent span id; NULL only for the root agent span.",
    "agent_id": "Agent identifier (config/agents.yaml).", "agent_version": "Agent version string.",
    "agent_release_seq": "Numeric release order of the version (use for ordering, not the string).",
    "release_seq": "Numeric release order of the version.", "scenario_id": "Scenario name that produced the event.",
    "kafka_topic": "Source Kafka topic.", "kafka_partition": "Source Kafka partition.", "kafka_offset": "Source Kafka offset.",
    "kafka_timestamp": "Kafka record timestamp (producer create time).", "ingested_at": "Spark micro-batch processing time.",
    "batch_id": "Spark micro-batch id that wrote the row.", "is_valid": "Passed structural validation.",
    "validation_error": "Quarantine reason (NULL when valid).", "raw_value": "Raw Kafka message value (JSON text).",
    "span_kind": "agent | planning | llm_call | retrieval | tool_call | policy_check | delegation.",
    "duration_ms": "Span duration in milliseconds (simulated for model/tool calls).",
    "status": "ok | error | timeout (spans); completed | failed | timeout (runs).",
    "error_category": "Error category, e.g. tool_timeout, tool_error, malformed_response, retrieval_error, policy_denied.",
    "attempt": "Attempt number (>1 = retry).", "depth": "Nesting depth in the trace (root = 1).",
    "input_tokens": "Input tokens (simulated by mock models).", "output_tokens": "Output tokens (simulated by mock models).",
    "total_tokens": "input_tokens + output_tokens.", "ttft_ms": "Time to first token (simulated).",
    "tool_name": "Requested tool.", "tool_args_valid": "Tool arguments validated against the tool's JSON Schema.",
    "tool_allowed": "Allowed by the runtime policy engine.", "policy_decision": "allow | deny | flag.",
    "data_classification": "public | internal | confidential | restricted.",
    "retrieved_doc_ids": "Ranked retrieved document ids.", "retrieval_scores": "Retrieval scores aligned with retrieved_doc_ids.",
    "dq_flags": "Row-level data-quality flags set by Spark (e.g. negative_duration, cost_unavailable).",
    "task_success": "Completed AND schema-valid AND correct answer AND correct tool calls (deterministic evaluators).",
    "latency_ms": "End-to-end run latency (root span duration).",
    "estimated_cost_usd": "ESTIMATED cost from config/pricing.yaml (illustrative local prices); NULL if unpriced.",
    "cost_source": "Pricing provenance: local_pricing_config:<version> or unavailable.",
    "injected_faults": "Synthetic ground-truth labels written by the generator; never used as detector input.",
    "max_consecutive_same_tool": "Longest run of identical consecutive tool calls (loop signal).",
    "tokens_per_second": "Output tokens / latency (derived in Spark).", "tool_error_rate": "(tool_errors + tool_timeouts) / tool_calls.",
    "evaluator_type": "deterministic | model_judge | human (never mixed).", "score": "Metric value / detector score.",
    "passed": "Whether the metric passed its threshold.", "rubric": "Rubric applied by the evaluator.",
    "evidence": "Evidence text (redacted for synthetic secrets).", "judge_model": "Judge model (model_judge records only).",
    "rule_id": "Policy rule id (SEC-001..SEC-008).", "severity": "low | medium | high | critical.",
    "action": "blocked (denied before execution) | flagged (detected and recorded) | allowed.",
    "detector": "Detector that produced the finding/alert.", "anomaly_type": "Alert type, e.g. suspected_loop, latency_spike.",
    "related_run_ids": "Runs supporting the alert.", "supporting_metrics": "Metric values behind the alert.",
    "explanation": "Human-readable explanation.",
}


def dictionary() -> None:
    from lakehouse.trino_client import run_query

    rows = run_query("""SELECT table_name, column_name, data_type FROM lakehouse.information_schema.columns
                        WHERE table_schema = 'analytics' ORDER BY table_name, ordinal_position""", max_rows=None).rows
    ddl = "\n".join(p.read_text(encoding="utf-8") for p in sorted((REPO_ROOT / "sql").glob("0[17]*.sql")))
    partitions = dict(re.findall(r"analytics\.(\w+) \(.*?partitioning = ARRAY\['(\w+)'\]", ddl, re.S))
    tables: dict[str, list] = {}
    for t, c, typ in rows:
        tables.setdefault(t, []).append((c, typ))
    out = ["# Data dictionary", "",
           f"Generated by `python -m docs.generate_docs dictionary` from the live lakehouse schema on "
           f"{datetime.now(timezone.utc):%Y-%m-%d}. Catalog `lakehouse`, schema `analytics`; Apache Iceberg (format v2) "
           "tables stored as Parquet/ZSTD on MinIO.", "",
           "Privacy & retention assumptions: all data is synthetic (fictional company, synthetic canary secrets). Raw "
           "prompts/answers are not stored unless CAPTURE_CONTENT=true (then redacted, truncated previews only). Kafka "
           "retains 7 days; Iceberg snapshots older than 7 days are expired by the lakehouse_maintenance DAG.", ""]
    for t in sorted(tables):
        out += [f"## `{t}`", "", TABLE_DOCS.get(t, ""), "",
                f"Partitioning: `{partitions[t]}`" if t in partitions else "Partitioning: none (small table)", "",
                "| Column | Type | Description |", "|---|---|---|"]
        out += [f"| `{c}` | {typ} | {COLUMN_DOCS.get(c, '')} |" for c, typ in tables[t]]
        out.append("")
    (DOCS / "DATA_DICTIONARY.md").write_text("\n".join(out), encoding="utf-8")
    print(f"DATA_DICTIONARY.md: {len(tables)} tables")


def _md_table(columns: list[str], rows: list[list], limit: int = 12) -> str:
    def cell(v):
        if isinstance(v, float):
            v = round(v, 4)
        s = json.dumps(v) if isinstance(v, (list, dict)) else ("NULL" if v is None else str(v))
        return s.replace("|", "\\|").replace("\n", " ")[:90]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"\n_{len(rows) - limit} more rows not shown (full result in docs/sql_outputs)._")
    return "\n".join(lines)


def showcase() -> None:
    from lakehouse.sql_catalog import load_file

    files = sorted((REPO_ROOT / "sql").glob("0[2-9]*.sql"))
    out = ["# SQL showcase", "",
           "Every query below is in the `sql/` directory, runs on Trino over Iceberg/Parquet, and is also served by "
           "the API's read-only query gallery. Sample outputs are **real results** exported from the current dataset "
           "with `python -m lakehouse.run_sql \"sql/0[2-9]*.sql\" --export docs/sql_outputs`; elapsed times are "
           "single-node Trino wall times. Parameters (`:days`, ...) are bound as prepared-statement parameters.", "",
           "Notes for readers: `1e0` literals are DOUBLE on purpose - `1.0` is DECIMAL(2,1) in Trino and `avg()` over "
           "it silently rounds rates to one decimal place. `approx_percentile` is approximate (see exact_vs_approx_p95).", "",
           "## Contents", ""]
    sections = []
    for f in files:
        named = [s for s in load_file(f) if s.name]
        out.append(f"- `{f.name}`: " + ", ".join(f"[{s.name}](#{s.name.replace('_', '-')})" for s in named))
        sections.append(f"\n## {f.name}\n")
        for st in named:
            res_path = OUTPUTS / f"{st.name}.json"
            sections += [f"### {st.name}", "", f"**{st.tags.get('title', '')}**", "",
                         f"- **Question:** {st.tags.get('question', '')}", f"- **SQL concepts:** {st.tags.get('concept', '')}",
                         f"- **Interpretation:** {st.tags.get('interpretation', '')}",
                         f"- **Parameters:** `{st.tags.get('params', 'none')}`", "", "```sql", st.sql, "```", ""]
            if res_path.exists():
                r = json.loads(res_path.read_text(encoding="utf-8"))
                stats = r.get("stats", {})
                sections.append(f"Sample output - {len(r['rows'])} row(s) shown from export, elapsed {r['elapsed_ms']:.0f} ms, "
                                f"processed rows {stats.get('processedRows')}:")
                sections.append("")
                if len(r["columns"]) == 1 and r["rows"] and isinstance(r["rows"][0][0], str) and "\n" in r["rows"][0][0]:
                    plan = r["rows"][0][0]
                    sections += ["```text", plan[:3500] + ("\n... (truncated)" if len(plan) > 3500 else ""), "```"]
                else:
                    sections.append(_md_table(r["columns"], r["rows"]))
                sections.append("")
            else:
                sections += ["_No exported output yet - run the export command above._", ""]
    (DOCS / "SQL_SHOWCASE.md").write_text("\n".join(out + sections), encoding="utf-8")
    print(f"SQL_SHOWCASE.md: {sum(1 for s in sections if s.startswith('### '))} queries")


def api() -> None:
    import httpx

    spec = httpx.get("http://localhost:8000/openapi.json", timeout=30).json()
    out = ["# API reference", "",
           f"Generated from the running API's OpenAPI document ({spec['info']['title']} {spec['info']['version']}). "
           "Interactive docs: http://localhost:8000/docs.", "",
           "## Conventions", "",
           "- JSON everywhere; errors are `{\"error\": {...}}` (validation, 500) or `{\"detail\": {\"code\", \"message\"}}` (domain errors).",
           "- 422 = invalid input (validated before any query runs); 404 = unknown id; 409 = conflict (e.g. a test run is already active); "
           "503 = a dependency (Trino/lakehouse, Postgres) is unavailable.",
           "- No endpoint executes caller-supplied SQL. Analytics use fixed queries or the curated read-only catalog with "
           "typed, prepared-statement parameters; Trino enforces a query timeout and the API limits rows.",
           "- Costs are estimates (config/pricing.yaml); agent latency/tokens are simulated by mock agents.", "",
           "## Endpoints", "", "| Method | Path | Summary |", "|---|---|---|"]
    for path, methods in sorted(spec["paths"].items()):
        for m, op in methods.items():
            summary = (op.get("description") or op.get("summary") or "").split("\n")[0]
            out.append(f"| {m.upper()} | `{path}` | {summary} |")
    out += ["", "## Parameters per endpoint", ""]
    for path, methods in sorted(spec["paths"].items()):
        for m, op in methods.items():
            params = op.get("parameters", [])
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            if not params and not body:
                continue
            out.append(f"### {m.upper()} {path}")
            for p in params:
                sch = p.get("schema", {})
                constraint = ", ".join(f"{k}={v}" for k, v in sch.items() if k in ("pattern", "minimum", "maximum", "default", "enum"))
                out.append(f"- `{p['name']}` ({p['in']}{', required' if p.get('required') else ''}) {constraint}")
            if body:
                out.append(f"- JSON body: `{body.get('$ref', body.get('type', 'object')).split('/')[-1]}`")
            out.append("")
    (DOCS / "API.md").write_text("\n".join(out), encoding="utf-8")
    print(f"API.md: {len(spec['paths'])} paths")


def _latest(pattern: str) -> dict | None:
    files = sorted(RESULTS.glob(pattern))
    return json.loads(files[-1].read_text()) | {"_file": files[-1].name} if files else None


def benchmarks() -> None:
    out = ["# Benchmark report (measured)", "",
           "Generated by `python -m docs.generate_docs benchmarks` from the JSON files in `benchmarks/results/`. "
           "Every number is copied from a measurement file named in each section; the methodology is in "
           "BENCHMARK_METHODOLOGY.md. Single machine running Docker Desktop - no multi-node scaling is claimed.", ""]
    pipes = sorted(RESULTS.glob("pipeline_benchmark_*.json"))
    if pipes:
        out += ["## End-to-end pipeline runs", "",
                "| Events | Producer events/s | Produce start -> all in lakehouse (s) | End-to-end events/s | Spark rows/s (span) | "
                "Max batch rows | Avg / max ingest lag (ms) | Quarantine = injected | Storage MB | Bytes/event | Source |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for f in pipes:
            r = json.loads(f.read_text())
            p, e, s, st, v = r["producer"], r["end_to_end"], r["spark"], r["storage"], r["validation"]
            out.append(f"| {p['events']:,} | {p['events_per_sec']:,} | {e['seconds_produce_start_to_all_in_lakehouse']} | "
                       f"{e['events_per_sec_end_to_end']:,} | {s['rows_per_sec_over_span']:,} | {s['largest_batch_rows']:,} | "
                       f"{s['avg_ingest_lag_ms']:.0f} / {s['max_ingest_lag_ms']:.0f} | {v['quarantine_matches_injected']} | "
                       f"{st['added_mb_total']} | {st['bytes_per_event']} | `{f.name}` |")
        last = json.loads(pipes[-1].read_text())
        env = last["environment"]
        out += ["", f"Environment: {env['host']['cpu_logical']} logical CPUs / {env['host']['ram_gb']} GB host RAM; Docker "
                f"{env['docker'].get('cpus')} CPUs / {env['docker'].get('memory_gib')} GiB; {env['stack']}.", "",
                "Agent latency of the largest run (simulated by mock agents): "
                f"p50 {last['agent_latency_this_run']['p50_ms']:.0f} ms, p95 {last['agent_latency_this_run']['p95_ms']:.0f} ms, "
                f"p99 {last['agent_latency_this_run']['p99_ms']:.0f} ms, success {last['agent_latency_this_run']['success_rate']:.4f}.", "",
                "Container memory at completion of the largest run:", "", "| Container | CPU | Memory |", "|---|---|---|"]
        out += [f"| {c['Name']} | {c['CPUPerc']} | {c['MemUsage']} |" for c in last["container_resources_at_completion"] if "Name" in c]
    sql = _latest("sql_benchmark_*.json")
    if sql:
        out += ["", f"## SQL performance experiment (`{sql['_file']}`)", "",
                f"Dataset at measurement time: {json.dumps(sql['dataset'])}. Median of {sql['tiers'][0]['runs']} runs after a warm-up.", "",
                "| Experiment | Query | Median ms | Rows read | Physical bytes read |", "|---|---|---|---|---|"]
        for exp in ("tiers", "pruning"):
            out += [f"| {exp} | {r['query']} | {r['wall_ms_median']} | {r['processed_rows']:,} | {r['physical_input_bytes']:,} |" for r in sql[exp]]
        lay = sql["layout"]
        out += ["", "Point lookup by `trace_id` (rows read per lookup):", "", "| trace_id | unsorted | sorted | sorted + 1 MB row groups |", "|---|---|---|---|"]
        for row in lay["lookups"]:
            out.append(f"| {row['trace_id'][:12]}... | {row['unsorted']['processed_rows']:,} | {row['sorted']['processed_rows']:,} | "
                       f"{row['sorted_small_rowgroups']['processed_rows']:,} |")
    comp = _latest("compaction_*.json")
    if comp:
        out += ["", f"## Iceberg compaction (`{comp['_file']}`)", "", "| Table | Files before | Files after |", "|---|---|---|"]
        out += [f"| {t['table']} | {t['files_before']} | {t['files_after']} |" for t in comp["tables"]]
        out += ["", f"Query latency before/after: {comp['query_latency_ms']['before']} / {comp['query_latency_ms']['after']} ms. {comp['interpretation']}"]
    evals = [json.loads(f.read_text()) | {"_file": f.name} for f in sorted(RESULTS.glob("detector_eval_*.json"))]
    hold = [e for e in evals if e["eval_scenario"].endswith("holdout")]
    if hold:
        h = hold[-1]
        out += ["", f"## Anomaly detectors on the held-out labelled scenario (`{h['_file']}`)", "",
                f"Model `{h['model_version']}` trained on {', '.join(h['model_training_scenarios'])} without labels; "
                f"{h['eval_runs']:,} runs, {h['positives']:,} positives.", "",
                "| Detector | Precision | Recall | F1 | FPR |", "|---|---|---|---|---|"]
        out += [f"| {k} | {m['precision']} | {m['recall']} | {m['f1']} | {m['false_positive_rate']} |" for k, m in h["overall"].items()]
        out += ["", f"Isolation Forest ROC-AUC: {h['isolation_forest_roc_auc']}.", "", "| Fault | Runs | Rules | IForest | Combined |", "|---|---|---|---|---|"]
        out += [f"| {f} | {m['runs']} | {m['rules']} | {m['isolation_forest']} | {m['combined']} |" for f, m in h["per_fault_recall"].items()]
        iw = h["incident_windows"]
        out += ["", f"Window rules: {sum(i['detected_by_window_rule'] for i in iw['incidents'])}/{len(iw['incidents'])} incident windows "
                f"detected; {iw['window_alerts_outside_incidents']} window alerts outside incidents."]
    sec = OUTPUTS / "security_detection_vs_ground_truth.json"
    if sec.exists():
        r = json.loads(sec.read_text())
        out += ["", "## Security rules vs synthetic ground truth (`docs/sql_outputs/security_detection_vs_ground_truth.json`)", "",
                _md_table(r["columns"], r["rows"], limit=20)]
    v1 = RESULTS / "detector_iteration_v1_measurement.json"
    if v1.exists():
        d = json.loads(v1.read_text())
        out += ["", "## Detector iteration log", "",
                f"Security rule v1 (before fix): {d['prompt_injection_rule_v1']['false_positive_findings_from_benign_doc_KB-020']} "
                f"false-positive findings from benign document KB-020; prompt-injection detection "
                f"{d['prompt_injection_detection_v1']['detection_rate_pct']}%. Fixes: " + "; ".join(d["fixes_applied_in_v2"]) + "."]
    (DOCS / "BENCHMARK_REPORT.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("BENCHMARK_REPORT.md written")


if __name__ == "__main__":
    targets = sys.argv[1:] or ["dictionary", "showcase", "api", "benchmarks"]
    for t in targets:
        {"dictionary": dictionary, "showcase": showcase, "api": api, "benchmarks": benchmarks}[t]()
