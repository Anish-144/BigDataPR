"""Run explorer and trace detail (lakehouse-backed)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query

from backend.app.services import query_service as qs

router = APIRouter(prefix="/api/v1", tags=["runs"])
T = "lakehouse.analytics"
ID = r"^[A-Za-z0-9_\-]{1,80}$"


@router.get("/runs")
def list_runs(
    days: int = Query(30, ge=1, le=3650),
    agent_id: str | None = Query(None, pattern=ID),
    agent_version: str | None = Query(None, pattern=r"^[0-9.]{1,16}$"),
    test_run_id: str | None = Query(None, pattern=ID),
    status: Literal["completed", "failed", "timeout"] | None = None,
    success: bool | None = None,
    has_findings: bool | None = None,
    min_latency_ms: float | None = Query(None, ge=0),
    run_id: str | None = Query(None, pattern=ID),
    sort: Literal["recent", "slowest", "most_tokens"] = "recent",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
) -> dict:
    """Search agent runs with filters and pagination. Every filter is a bound parameter."""
    where = ["m.event_date >= current_date - (? * INTERVAL '1' DAY)"]
    params: list = [days]
    for col, val in (("agent_id", agent_id), ("agent_version", agent_version), ("test_run_id", test_run_id),
                     ("status", status), ("run_id", run_id)):
        if val is not None:
            where.append(f"m.{col} = ?")  # column names come from this fixed tuple, never from the caller
            params.append(val)
    if success is not None:
        where.append("m.task_success = ?")
        params.append(success)
    if min_latency_ms is not None:
        where.append("m.latency_ms >= ?")
        params.append(min_latency_ms)
    if has_findings is not None:
        where.append(("" if has_findings else "NOT ") +
                     f"EXISTS (SELECT 1 FROM {T}.agent_security_findings f WHERE f.run_id = m.run_id)")
    order = {"recent": "m.event_time DESC", "slowest": "m.latency_ms DESC", "most_tokens": "m.total_tokens DESC"}[sort]
    sql = f"""
        SELECT m.run_id, m.trace_id, m.test_run_id, m.scenario_id, m.agent_id, m.agent_name, m.agent_version,
               m.model_name, m.workload_type, m.difficulty, m.status, m.task_success, m.error_category,
               m.event_time, m.latency_ms, m.ttft_ms, m.total_tokens, m.estimated_cost_usd, m.tool_calls,
               m.tool_errors, m.retries, m.span_count, m.policy_denials, m.injected_faults
        FROM {T}.agent_run_metrics m
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        OFFSET ? LIMIT ?"""
    rows = qs.sql_rows(sql, params + [offset, limit])
    return {"limit": limit, "offset": offset, "rows": rows, "has_more": len(rows) == limit}


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str = Path(..., pattern=r"^[0-9a-f]{32}$")) -> dict:
    """Full trace: spans (waterfall), run summary, evaluations, security findings and anomaly alerts."""
    spans = qs.sql_rows(f"""
        SELECT span_id, parent_span_id, span_kind, span_name, start_time, end_time, duration_ms, status,
               error_category, step_index, attempt, depth, model_name, input_tokens, output_tokens, ttft_ms,
               tool_name, tool_args_valid, tool_allowed, policy_decision, data_classification,
               retrieved_doc_ids, retrieval_scores, top_k, delegated_agent_id, attributes, dq_flags
        FROM {T}.agent_spans WHERE trace_id = ? ORDER BY start_time, step_index""", [trace_id])
    if not spans:
        raise HTTPException(404, {"code": "trace_not_found", "message": f"no spans for trace {trace_id}"})
    run = qs.sql_rows(f"SELECT * FROM {T}.agent_run_metrics WHERE trace_id = ? LIMIT 1", [trace_id])
    evals = qs.sql_rows(f"""
        SELECT evaluator_name, evaluator_version, evaluator_type, metric_name, score, passed, threshold, rubric, evidence
        FROM {T}.agent_evaluation_results WHERE trace_id = ? ORDER BY evaluator_name, metric_name""", [trace_id])
    findings = qs.sql_rows(f"""
        SELECT finding_id, rule_id, rule_name, category, severity, span_id, tool_name, action, detector, evidence,
               policy_version, event_time
        FROM {T}.agent_security_findings WHERE trace_id = ? ORDER BY event_time""", [trace_id])
    alerts = qs.sql_rows(f"""
        SELECT alert_id, detector, detector_version, anomaly_type, severity, score, explanation, supporting_metrics
        FROM (SELECT *, row_number() OVER (PARTITION BY alert_id ORDER BY ingested_at) AS rn
              FROM {T}.agent_anomaly_alerts WHERE trace_id = ? OR contains(related_trace_ids, ?))
        WHERE rn = 1""", [trace_id, trace_id])
    return {"trace_id": trace_id, "run": run[0] if run else None, "spans": spans, "evaluations": evals,
            "security_findings": findings, "anomaly_alerts": alerts}


@router.get("/runs/{run_id}")
def get_run(run_id: str = Path(..., pattern=ID)) -> dict:
    rows = qs.sql_rows(f"SELECT trace_id FROM {T}.agent_run_metrics WHERE run_id = ? LIMIT 1", [run_id])
    if not rows:
        raise HTTPException(404, {"code": "run_not_found", "message": f"run {run_id} not found"})
    return get_trace(rows[0]["trace_id"])
