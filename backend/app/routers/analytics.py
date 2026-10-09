from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.app.services import query_service as qs
from lakehouse.sql_catalog import SQL_DIR, load_file
from lakehouse.trino_client import run_query

router = APIRouter(prefix="/api/v1", tags=["analytics"])
T = "lakehouse.analytics"
Days = Query(30, ge=1, le=3650, description="look-back window in days (by event_date, UTC)")


def bundle(names: list[str], params: dict[str, Any]) -> dict:
    out = {}
    for n in names:
        st = qs.catalog()[n]
        out[n] = qs.run_named(n, {k: v for k, v in params.items() if k in st.defaults})
    return out


@router.get("/overview")
def overview(days: int = Days) -> dict:
    """Headline KPIs computed live from the lakehouse."""
    window = "event_date >= current_date - (? * INTERVAL '1' DAY)"
    runs = qs.sql_rows(f"""
        SELECT count(*) AS total_runs, count(DISTINCT test_run_id) AS test_runs,
               avg(IF(task_success, 1e0, 0e0)) AS success_rate,
               approx_percentile(latency_ms, 0.95) AS p95_latency_ms,
               sum(total_tokens) AS total_tokens, sum(estimated_cost_usd) AS est_cost_usd,
               count_if(status <> 'completed') AS failed_runs
        FROM {T}.agent_run_metrics WHERE {window}""", [days])[0]
    events = qs.sql_scalar(f"SELECT count(*) FROM {T}.raw_agent_events WHERE {window}", [days])
    findings = qs.sql_rows(f"""
        SELECT count(*) AS findings, count_if(severity = 'critical') AS critical
        FROM {T}.agent_security_findings WHERE {window}""", [days])[0]
    alerts = qs.sql_rows(f"""
        SELECT count(DISTINCT alert_id) AS alerts,
               count(DISTINCT alert_id) FILTER (WHERE severity IN ('high', 'critical')) AS high_or_critical
        FROM {T}.agent_anomaly_alerts WHERE {window}""", [days])[0]
    dq = qs.sql_scalar(f"SELECT count(*) FROM {T}.dead_letter_events WHERE ingest_date >= current_date - (? * INTERVAL '1' DAY)", [days])
    trend = qs.sql_rows(f"""
        SELECT date_trunc('hour', event_time) AS hour, count(*) AS runs,
               avg(IF(task_success, 1e0, 0e0)) AS success_rate, approx_percentile(latency_ms, 0.95) AS p95_latency_ms
        FROM {T}.agent_run_metrics WHERE {window}
        GROUP BY 1 ORDER BY 1""", [days])
    return {
        "days": days,
        "runs": runs,
        "events": events,
        "security": findings,
        "anomalies": alerts,
        "quarantined_records": dq,
        "hourly_trend": trend,
        "cost_note": "estimated_cost_usd uses config/pricing.yaml (illustrative local prices for mock models)",
    }


@router.get("/analytics/performance")
def performance(days: int = Days) -> dict:
    return bundle(["latency_percentiles_by_version", "tool_performance", "error_categories",
                   "token_and_cost_summary", "hourly_throughput", "streaming_batch_stats"], {"days": days})


@router.get("/analytics/quality")
def quality(days: int = Days) -> dict:
    return bundle(["quality_metrics_by_version", "retrieval_quality_by_version", "cost_per_successful_task"], {"days": days})


@router.get("/analytics/regressions")
def regressions(days: int = Days, scenario: str = Query("regression", pattern=r"^[A-Za-z0-9_\-]{1,64}$")) -> dict:
    out = bundle(["version_regression_lag", "prompt_model_comparison"], {"days": days})
    out["cohort_ab_comparison"] = qs.run_named("cohort_ab_comparison", {"days": days, "scenario": scenario})
    return out


@router.get("/analytics/comparison")
def comparison(days: int = Days, versions: str = Query(..., description="comma-separated agent_id@version keys, 2-6 items",
                                                         pattern=r"^[a-z0-9\-]+@[0-9.]+(,[a-z0-9\-]+@[0-9.]+){1,5}$")) -> dict:
    """Side-by-side comparison of 2-6 agent versions across quality, latency, cost, anomalies and security."""
    keys = [v.split("@") for v in versions.split(",")]
    placeholders = ", ".join(["(?, ?)"] * len(keys))
    flat = [x for k in keys for x in k]
    rows = qs.sql_rows(f"""
        WITH sel(agent_id, agent_version) AS (VALUES {placeholders}),
        runs AS (
            SELECT m.agent_id, m.agent_version, max(m.agent_name) AS agent_name, max(m.model_name) AS model_name,
                   max(m.prompt_version) AS prompt_version, count(*) AS runs,
                   avg(IF(m.task_success, 1e0, 0e0)) AS success_rate,
                   approx_percentile(m.latency_ms, 0.5) AS p50_latency_ms,
                   approx_percentile(m.latency_ms, 0.95) AS p95_latency_ms,
                   avg(m.total_tokens) AS avg_tokens, sum(m.estimated_cost_usd) AS est_cost_usd,
                   sum(m.estimated_cost_usd) / nullif(count_if(m.task_success), 0) AS est_cost_per_success,
                   avg(m.retries) AS avg_retries
            FROM {T}.agent_run_metrics m JOIN sel ON sel.agent_id = m.agent_id AND sel.agent_version = m.agent_version
            WHERE m.event_date >= current_date - (? * INTERVAL '1' DAY)
            GROUP BY m.agent_id, m.agent_version
        ),
        evals AS (
            SELECT e.agent_id, e.agent_version,
                   avg(e.score) FILTER (WHERE e.metric_name = 'exact_match') AS exact_match,
                   avg(e.score) FILTER (WHERE e.metric_name = 'schema_validity') AS schema_validity,
                   avg(e.score) FILTER (WHERE e.metric_name = 'recall_at_k') AS recall_at_k,
                   avg(e.score) FILTER (WHERE e.metric_name = 'hallucination_flag') AS hallucination_flag_rate
            FROM {T}.agent_evaluation_results e JOIN sel ON sel.agent_id = e.agent_id AND sel.agent_version = e.agent_version
            WHERE e.event_date >= current_date - (? * INTERVAL '1' DAY) AND e.evaluator_type = 'deterministic'
            GROUP BY e.agent_id, e.agent_version
        ),
        sec AS (
            SELECT s.agent_id, s.agent_version, count(*) AS security_findings,
                   count_if(s.severity = 'critical') AS critical_findings
            FROM {T}.agent_security_findings s JOIN sel ON sel.agent_id = s.agent_id AND sel.agent_version = s.agent_version
            WHERE s.event_date >= current_date - (? * INTERVAL '1' DAY)
            GROUP BY s.agent_id, s.agent_version
        ),
        anom AS (
            SELECT a.agent_id, a.agent_version, count(*) AS anomaly_alerts
            FROM {T}.agent_anomaly_alerts a JOIN sel ON sel.agent_id = a.agent_id AND sel.agent_version = a.agent_version
            WHERE a.event_date >= current_date - (? * INTERVAL '1' DAY)
            GROUP BY a.agent_id, a.agent_version
        )
        SELECT r.*, e.exact_match, e.schema_validity, e.recall_at_k, e.hallucination_flag_rate,
               coalesce(s.security_findings, 0) AS security_findings, coalesce(s.critical_findings, 0) AS critical_findings,
               1000e0 * coalesce(s.security_findings, 0) / r.runs AS findings_per_1k_runs,
               coalesce(a.anomaly_alerts, 0) AS anomaly_alerts
        FROM runs r
        LEFT JOIN evals e ON e.agent_id = r.agent_id AND e.agent_version = r.agent_version
        LEFT JOIN sec s   ON s.agent_id = r.agent_id AND s.agent_version = r.agent_version
        LEFT JOIN anom a  ON a.agent_id = r.agent_id AND a.agent_version = r.agent_version
        ORDER BY r.agent_id, r.agent_version""", flat + [days, days, days, days])
    return {"days": days, "versions": versions.split(","), "rows": rows,
            "cost_note": "estimated costs from config/pricing.yaml (local illustrative pricing)"}


@router.get("/analytics/data-quality")
def data_quality(days: int = Days) -> dict:
    return bundle(["dq_scorecard", "dq_quarantine_reasons", "dq_duplicate_events", "dq_orphan_spans",
                   "dq_run_span_consistency", "dq_timestamp_checks"], {"days": days})


@router.get("/analytics/sql-showcase")
def sql_showcase() -> dict:
    """The curated, read-only query gallery (SQL text + analytical question + interpretation)."""
    items = [qs.describe(st) for st in qs.catalog().values()]
    return {"count": len(items), "queries": sorted(items, key=lambda q: (q["file"], q["name"]))}


@router.post("/analytics/sql-showcase/{name}/run")
def run_showcase_query(name: str, params: dict[str, Any] = Body(default_factory=dict)) -> dict:
    """Execute one catalog query with validated, prepared-statement parameters."""
    return qs.run_named(name, params)


@router.post("/analytics/summary-tables/refresh")
def refresh_summary_tables(days: int = Query(60, ge=1, le=3650)) -> dict:
    """Rebuild hourly/daily summary partitions for the last N days (sql/07_summary_tables.sql DML)."""
    steps = []
    for st in load_file(SQL_DIR / "07_summary_tables.sql"):
        if st.name or not st.sql.lstrip().upper().startswith(("DELETE", "INSERT", "CREATE")):
            continue
        sql, params = st.bind({"days": days} if "days" in st.defaults else {})
        res = run_query(sql, params or None)
        steps.append({"statement": st.sql.split("\n", 1)[0][:80], "elapsed_ms": res.elapsed_ms,
                      "rows": res.rows[0][0] if res.rows else None})
    return {"days": days, "steps": steps}
