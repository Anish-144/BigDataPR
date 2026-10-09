"""Anomaly center: alerts (lakehouse) + analyst feedback (PostgreSQL) + detector evaluation."""

from __future__ import annotations

import json
from collections import Counter
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app import db
from backend.app.services import query_service as qs
from common.settings import REPO_ROOT, get_settings

router = APIRouter(prefix="/api/v1", tags=["anomalies"])
T = "lakehouse.analytics"
ALERT_ID = r"^A-[0-9a-f]{16}$"
FALSE_POSITIVE_NOTE = ("An anomaly is an unusual execution pattern worth investigating. It is not automatically a "
                       "bug or an attack; rule thresholds and the Isolation Forest have measured false-positive rates "
                       "(see detector evaluation).")


def _feedback(alert_ids: list[str]) -> dict[str, list[dict]]:
    if not alert_ids:
        return {}
    try:
        with db.session_factory()() as s:
            rows = s.scalars(select(db.AlertFeedback).where(db.AlertFeedback.alert_id.in_(alert_ids))
                             .order_by(db.AlertFeedback.created_at)).all()
    except Exception:
        return {}
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r.alert_id, []).append({"verdict": r.verdict, "note": r.note, "reviewer": r.reviewer,
                                               "created_at": r.created_at.isoformat()})
    return out


@router.get("/anomalies")
def list_alerts(
    days: int = Query(30, ge=1, le=3650),
    severity: Literal["low", "medium", "high", "critical"] | None = None,
    anomaly_type: str | None = Query(None, pattern=r"^[a-z_]{3,40}$"),
    detector: str | None = Query(None, pattern=r"^[a-z_:]{3,60}$"),
    agent_id: str | None = Query(None, pattern=r"^[a-z0-9\-]{3,64}$"),
    test_run_id: str | None = Query(None, pattern=r"^TR-\d{8}-[0-9a-f]{6}$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
) -> dict:
    where, params = ["event_date >= current_date - (? * INTERVAL '1' DAY)"], [days]
    for col, val in (("severity", severity), ("anomaly_type", anomaly_type), ("detector", detector),
                     ("agent_id", agent_id), ("test_run_id", test_run_id)):
        if val is not None:
            where.append(f"{col} = ?")  # fixed column names
            params.append(val)
    rows = qs.sql_rows(f"""
        SELECT alert_id, detector, detector_version, anomaly_type, severity, score, agent_id, agent_name, agent_version,
               test_run_id, run_id, trace_id, window_start, window_end, related_run_ids, supporting_metrics, explanation,
               event_time
        FROM (SELECT *, row_number() OVER (PARTITION BY alert_id ORDER BY ingested_at) AS rn
              FROM {T}.agent_anomaly_alerts WHERE {' AND '.join(where)})
        WHERE rn = 1
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, event_time DESC
        OFFSET ? LIMIT ?""", params + [offset, limit])
    fb = _feedback([r["alert_id"] for r in rows])
    for r in rows:
        r["feedback"] = fb.get(r["alert_id"], [])
    return {"rows": rows, "limit": limit, "offset": offset, "has_more": len(rows) == limit, "note": FALSE_POSITIVE_NOTE}


@router.get("/anomalies/summary")
def summary(days: int = Query(30, ge=1, le=3650)) -> dict:
    by = qs.sql_rows(f"""
        SELECT detector, anomaly_type, severity, count(DISTINCT alert_id) AS alerts, count(DISTINCT agent_id) AS agents
        FROM {T}.agent_anomaly_alerts WHERE event_date >= current_date - (? * INTERVAL '1' DAY)
        GROUP BY 1, 2, 3 ORDER BY alerts DESC""", [days])
    by_agent = qs.sql_rows(f"""
        SELECT agent_id, agent_version, count(DISTINCT alert_id) AS alerts,
               count(DISTINCT alert_id) FILTER (WHERE severity IN ('high', 'critical')) AS high_or_critical
        FROM {T}.agent_anomaly_alerts WHERE event_date >= current_date - (? * INTERVAL '1' DAY)
        GROUP BY 1, 2 ORDER BY alerts DESC""", [days])
    try:
        with db.session_factory()() as s:
            fb = s.scalars(select(db.AlertFeedback)).all()
        verdicts = Counter(f.verdict for f in fb)
    except Exception:
        verdicts = Counter()
    return {"by_detector_type_severity": by, "by_agent_version": by_agent, "feedback_verdicts": dict(verdicts),
            "detector_evaluation": latest_evaluation(), "model": model_info(), "note": FALSE_POSITIVE_NOTE}


@router.get("/anomalies/{alert_id}")
def get_alert(alert_id: str = Path(..., pattern=ALERT_ID)) -> dict:
    rows = qs.sql_rows(f"SELECT * FROM {T}.agent_anomaly_alerts WHERE alert_id = ? ORDER BY ingested_at LIMIT 1", [alert_id])
    if not rows:
        raise HTTPException(404, {"code": "alert_not_found", "message": alert_id})
    alert = rows[0]
    related = alert.get("related_run_ids") or ([alert["run_id"]] if alert.get("run_id") else [])
    runs = []
    if related:
        ph = ", ".join(["?"] * min(len(related), 50))
        runs = qs.sql_rows(f"""
            SELECT run_id, trace_id, agent_id, agent_version, status, task_success, latency_ms, total_tokens, tool_calls,
                   tool_errors, tool_timeouts, retries, max_consecutive_same_tool, error_category, event_time
            FROM {T}.agent_run_metrics WHERE run_id IN ({ph}) ORDER BY event_time""", related[:50])
    return {"alert": alert, "related_runs": runs, "feedback": _feedback([alert_id]).get(alert_id, []),
            "note": FALSE_POSITIVE_NOTE}


class Feedback(BaseModel):
    verdict: Literal["useful", "noisy", "acknowledged"]
    note: str | None = Field(None, max_length=1000)
    reviewer: str = Field("analyst", pattern=r"^[A-Za-z0-9_.\-]{1,64}$")


@router.post("/anomalies/{alert_id}/feedback", status_code=201)
def add_feedback(body: Feedback, alert_id: str = Path(..., pattern=ALERT_ID)) -> dict:
    """Record whether an alert was useful or noisy (kept for detector review; never auto-applied)."""
    exists = qs.sql_scalar(f"SELECT count(*) FROM {T}.agent_anomaly_alerts WHERE alert_id = ?", [alert_id])
    if not exists:
        raise HTTPException(404, {"code": "alert_not_found", "message": alert_id})
    with db.session_factory()() as s:
        rec = db.AlertFeedback(alert_id=alert_id, verdict=body.verdict, note=body.note, reviewer=body.reviewer)
        s.add(rec)
        s.commit()
        return {"id": rec.id, "alert_id": alert_id, "verdict": body.verdict, "created_at": rec.created_at.isoformat()}


class ScoreRequest(BaseModel):
    test_run_id: str | None = Field(None, pattern=r"^TR-\d{8}-[0-9a-f]{6}$")
    since_minutes: int | None = Field(None, ge=1, le=60 * 24 * 30)


@router.post("/anomalies/score")
def score_now(body: ScoreRequest) -> dict:
    """Run the rule + Isolation Forest detectors over a test run (or recent runs) and publish alerts via Kafka."""
    if not body.test_run_id and not body.since_minutes:
        raise HTTPException(422, {"code": "scope_required", "message": "give test_run_id or since_minutes"})
    from ml.score_events import score

    try:
        return score([body.test_run_id] if body.test_run_id else None, None, body.since_minutes)
    except FileNotFoundError as exc:
        raise HTTPException(409, {"code": "model_not_trained", "message": str(exc)}) from exc


def latest_evaluation() -> dict | None:
    files = sorted(get_settings().results_dir.glob("detector_eval_*.json"))
    evals = [json.loads(f.read_text()) | {"file": f.name} for f in files]
    holdout = [e for e in evals if e.get("eval_scenario", "").endswith("holdout")]
    pick = (holdout or evals or [None])[-1]
    return pick


def model_info() -> dict | None:
    p = REPO_ROOT / "models" / "latest.json"
    if not p.exists():
        return None
    meta = json.loads(p.read_text())
    meta.pop("baseline", None)
    return meta


@router.get("/ml/detector-evaluation")
def detector_evaluation() -> dict:
    return {"evaluation": latest_evaluation(), "model": model_info()}
