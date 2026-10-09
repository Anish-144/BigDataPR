"""Security & governance: findings with policy rule and trace evidence, policy-as-code view."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from backend.app.services import query_service as qs
from common.config import load_policy

router = APIRouter(prefix="/api/v1/security", tags=["security"])
T = "lakehouse.analytics"
NOTE = ("Findings come from deterministic policy rules and content detectors applied to SYNTHETIC test data. A finding "
        "is evidence to investigate, not proof of malicious intent. Remediation is always human-approved.")


@router.get("/findings")
def findings(
    days: int = Query(30, ge=1, le=3650),
    severity: Literal["low", "medium", "high", "critical"] | None = None,
    rule_id: str | None = Query(None, pattern=r"^SEC-\d{3}$"),
    category: str | None = Query(None, pattern=r"^[a-z_]{3,40}$"),
    action: Literal["blocked", "flagged", "allowed"] | None = None,
    agent_id: str | None = Query(None, pattern=r"^[a-z0-9\-]{3,64}$"),
    test_run_id: str | None = Query(None, pattern=r"^TR-\d{8}-[0-9a-f]{6}$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
) -> dict:
    where, params = ["f.event_date >= current_date - (? * INTERVAL '1' DAY)"], [days]
    for col, val in (("severity", severity), ("rule_id", rule_id), ("category", category), ("action", action),
                     ("agent_id", agent_id), ("test_run_id", test_run_id)):
        if val is not None:
            where.append(f"f.{col} = ?")  # fixed column names
            params.append(val)
    rows = qs.sql_rows(f"""
        SELECT f.finding_id, f.event_time, f.rule_id, f.rule_name, f.category, f.severity, f.action, f.detector,
               f.agent_id, f.agent_version, f.test_run_id, f.run_id, f.trace_id, f.span_id, f.tool_name, f.evidence,
               f.policy_version, p.description AS rule_description,
               s.span_kind, s.span_name, s.policy_decision, s.data_classification
        FROM {T}.agent_security_findings f
        LEFT JOIN {T}.dim_policy_rules p ON p.rule_id = f.rule_id
        LEFT JOIN {T}.agent_spans s ON s.trace_id = f.trace_id AND s.span_id = f.span_id AND s.event_date = f.event_date
        WHERE {' AND '.join(where)}
        ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, f.event_time DESC
        OFFSET ? LIMIT ?""", params + [offset, limit])
    return {"rows": rows, "limit": limit, "offset": offset, "has_more": len(rows) == limit, "note": NOTE}


@router.get("/summary")
def summary(days: int = Query(30, ge=1, le=3650)) -> dict:
    by_rule = qs.run_named("findings_by_rule_and_severity", {"days": days})
    detection = qs.run_named("security_detection_vs_ground_truth", {"days": days})
    risk = qs.run_named("highest_risk_scenarios", {"days": days})
    by_agent = qs.sql_rows(f"""
        SELECT agent_id, agent_version, count(*) AS findings, count_if(severity = 'critical') AS critical,
               count_if(action = 'blocked') AS blocked, count(DISTINCT run_id) AS affected_runs
        FROM {T}.agent_security_findings WHERE event_date >= current_date - (? * INTERVAL '1' DAY)
        GROUP BY 1, 2 ORDER BY findings DESC""", [days])
    return {"by_rule": by_rule, "detection_vs_ground_truth": detection, "highest_risk": risk, "by_agent": by_agent,
            "note": NOTE}


@router.get("/policy")
def policy() -> dict:
    """The active policy-as-code configuration (config/policies.yaml)."""
    return {"policy": load_policy(), "source": "config/policies.yaml", "note": NOTE}
