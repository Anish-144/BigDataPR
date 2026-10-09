"""Wire-format schemas used by the Spark job to parse Kafka JSON.

Pure Python (no PySpark / pydantic import) so it can be unit-tested on the host:
tests/unit/test_contracts.py asserts that every DDL here matches the Pydantic
models in generator/event_schema.py field-for-field. Timestamps are parsed as
STRING and cast explicitly so that unparseable values can be detected and
quarantined instead of silently becoming NULL.
"""

from __future__ import annotations

ENVELOPE_DDL = (
    "event_id STRING, event_type STRING, schema_version STRING, event_time STRING, producer STRING, "
    "test_run_id STRING, run_id STRING, trace_id STRING, agent_id STRING, agent_version STRING, "
    "scenario_id STRING, payload STRING"
)

PAYLOAD_DDL: dict[str, str] = {
    "test_run": (
        "test_run_name STRING, status STRING, seed BIGINT, requested_tasks BIGINT, workers BIGINT, "
        "time_mode STRING, scenario_file STRING, workload_mix STRING, fault_profile STRING, started_at STRING, "
        "ended_at STRING, sim_window_start STRING, sim_window_end STRING, total_runs BIGINT, total_events BIGINT, "
        "triggered_by STRING, notes STRING"
    ),
    "span.completed": (
        "span_id STRING, parent_span_id STRING, span_kind STRING, span_name STRING, start_time STRING, "
        "end_time STRING, duration_ms DOUBLE, status STRING, error_category STRING, step_index BIGINT, "
        "attempt BIGINT, model_name STRING, input_tokens BIGINT, output_tokens BIGINT, ttft_ms DOUBLE, "
        "tool_name STRING, tool_args_valid BOOLEAN, tool_allowed BOOLEAN, policy_decision STRING, "
        "data_classification STRING, retrieved_doc_ids ARRAY<STRING>, retrieval_scores ARRAY<DOUBLE>, "
        "top_k BIGINT, delegated_agent_id STRING, attributes MAP<STRING,STRING>"
    ),
    "run.metrics": (
        "agent_name STRING, agent_release_seq BIGINT, model_name STRING, prompt_version STRING, "
        "workload_type STRING, difficulty STRING, task_id STRING, status STRING, task_success BOOLEAN, "
        "start_time STRING, end_time STRING, latency_ms DOUBLE, ttft_ms DOUBLE, input_tokens BIGINT, "
        "output_tokens BIGINT, llm_calls BIGINT, tool_calls BIGINT, tool_errors BIGINT, tool_timeouts BIGINT, "
        "retries BIGINT, span_count BIGINT, max_depth BIGINT, distinct_tools BIGINT, "
        "max_consecutive_same_tool BIGINT, avg_tool_latency_ms DOUBLE, retrieval_count BIGINT, "
        "policy_denials BIGINT, error_category STRING, estimated_cost_usd DOUBLE, cost_source STRING, "
        "injected_faults ARRAY<STRING>, worker_id STRING, routing_strategy STRING"
    ),
    "worker.resource": (
        "worker_id STRING, cpu_percent DOUBLE, memory_mb DOUBLE, tasks_completed BIGINT, events_emitted BIGINT, "
        "events_per_sec DOUBLE, interval_s DOUBLE"
    ),
    "evaluation.result": (
        "evaluation_id STRING, evaluator_name STRING, evaluator_version STRING, evaluator_type STRING, "
        "metric_name STRING, score DOUBLE, passed BOOLEAN, threshold DOUBLE, rubric STRING, evidence STRING, "
        "judge_model STRING"
    ),
    "security.finding": (
        "finding_id STRING, rule_id STRING, rule_name STRING, category STRING, severity STRING, span_id STRING, "
        "tool_name STRING, action STRING, policy_version STRING, detector STRING, evidence STRING"
    ),
    "anomaly.alert": (
        "alert_id STRING, detector STRING, detector_version STRING, anomaly_type STRING, severity STRING, "
        "score DOUBLE, window_start STRING, window_end STRING, agent_name STRING, related_run_ids ARRAY<STRING>, "
        "related_trace_ids ARRAY<STRING>, supporting_metrics MAP<STRING,DOUBLE>, explanation STRING"
    ),
}

# event_type -> payload DDL key
EVENT_PAYLOAD: dict[str, str] = {
    "test_run.started": "test_run",
    "test_run.completed": "test_run",
    "span.completed": "span.completed",
    "run.metrics": "run.metrics",
    "worker.resource": "worker.resource",
    "evaluation.result": "evaluation.result",
    "security.finding": "security.finding",
    "anomaly.alert": "anomaly.alert",
}

EVENT_TOPIC: dict[str, str] = {
    "test_run.started": "agent-traces",
    "test_run.completed": "agent-traces",
    "span.completed": "agent-traces",
    "run.metrics": "agent-metrics",
    "worker.resource": "agent-metrics",
    "evaluation.result": "agent-evaluations",
    "security.finding": "agent-security-events",
    "anomaly.alert": "agent-alerts",
}

SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")

# Envelope fields required per event type (mirrors event_schema.REQUIRED_CONTEXT).
REQUIRED_CONTEXT: dict[str, tuple[str, ...]] = {
    "test_run.started": ("test_run_id",),
    "test_run.completed": ("test_run_id",),
    "span.completed": ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    "run.metrics": ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    "worker.resource": ("test_run_id",),
    "evaluation.result": ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    "security.finding": ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    "anomaly.alert": (),
}

# Payload fields that must be non-null (after parsing) for an event to be accepted.
REQUIRED_PAYLOAD: dict[str, tuple[str, ...]] = {
    "test_run": ("test_run_name", "status", "started_at"),
    "span.completed": ("span_id", "span_kind", "start_time", "end_time", "duration_ms", "status"),
    "run.metrics": ("status", "task_success", "latency_ms", "input_tokens", "output_tokens"),
    "worker.resource": ("worker_id",),
    "evaluation.result": ("evaluation_id", "evaluator_name", "metric_name"),
    "security.finding": ("finding_id", "rule_id", "severity"),
    "anomaly.alert": ("alert_id", "detector", "anomaly_type", "severity"),
}

TIMESTAMP_FIELDS: dict[str, tuple[str, ...]] = {
    "test_run": ("started_at", "ended_at", "sim_window_start", "sim_window_end"),
    "span.completed": ("start_time", "end_time"),
    "run.metrics": ("start_time", "end_time"),
    "worker.resource": (),
    "evaluation.result": (),
    "security.finding": (),
    "anomaly.alert": ("window_start", "window_end"),
}


def ddl_fields(ddl: str) -> list[tuple[str, str]]:
    """Split a Spark DDL schema string into (name, type) pairs (handles nested <...>)."""
    fields, depth, current = [], 0, ""
    for ch in ddl:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            fields.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        fields.append(current.strip())
    out = []
    for f in fields:
        name, typ = f.split(" ", 1)
        out.append((name, typ.strip().replace(" ", "")))
    return out
