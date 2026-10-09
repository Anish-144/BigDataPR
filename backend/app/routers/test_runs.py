"""Testing lab: scenarios, test-run control, regression gate."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from pydantic import BaseModel, Field, field_validator

from backend.app.services import query_service as qs
from backend.app.services import test_runner
from common.settings import REPO_ROOT
from evaluation import regression_gate
from generator.agents.base import ALL_FAULTS
from generator.runner import MixEntry, TestRunConfig

router = APIRouter(prefix="/api/v1", tags=["testing-lab"])
T = "lakehouse.analytics"
SCENARIO_DIR = REPO_ROOT / "generator" / "scenarios"
TR_ID = r"^TR-\d{8}-[0-9a-f]{6}$"


def _scenarios() -> dict[str, dict]:
    out = {}
    for p in sorted(SCENARIO_DIR.glob("*.yaml")):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        out[p.stem] = {"file": p.relative_to(REPO_ROOT).as_posix(), **data}
    return out


@router.get("/scenarios")
def list_scenarios() -> dict:
    return {"scenarios": [{"id": k, **v} for k, v in _scenarios().items()], "faults": list(ALL_FAULTS)}


class TestRunRequest(BaseModel):
    __test__ = False
    scenario: str = Field("smoke", pattern=r"^[a-z0-9_]{1,40}$")
    name: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-]{1,40}$")
    tasks: int | None = Field(None, ge=1, le=200_000)
    workers: int | None = Field(None, ge=1, le=4)
    seed: int | None = Field(None, ge=0, le=2**31)
    time_mode: Literal["simulated", "realtime"] | None = None
    sim_days: float | None = Field(None, gt=0, le=60)
    rate_per_sec: float | None = Field(None, ge=0, le=2000)
    fault_profile: dict[str, float] | None = None
    workload_mix: list[MixEntry] | None = None
    dirty_rate: float | None = Field(None, ge=0, le=0.2)
    notes: str | None = Field(None, max_length=200)

    @field_validator("fault_profile")
    @classmethod
    def check_faults(cls, v):
        if v is None:
            return v
        unknown = set(v) - set(ALL_FAULTS)
        if unknown:
            raise ValueError(f"unknown faults {sorted(unknown)}; allowed: {list(ALL_FAULTS)}")
        if any(not 0 <= r <= 0.5 for r in v.values()):
            raise ValueError("fault rates must be within [0, 0.5]")
        return v


@router.post("/test-runs", status_code=202)
def start_test_run(body: TestRunRequest) -> dict:
    """Start a test run (same engine as the CLI) in the background; telemetry flows through Kafka."""
    scen = _scenarios().get(body.scenario)
    if scen is None:
        raise HTTPException(404, {"code": "unknown_scenario", "message": body.scenario, "available": list(_scenarios())})
    overrides = body.model_dump(exclude_none=True, exclude={"scenario"})
    try:
        cfg = TestRunConfig.from_yaml(REPO_ROOT / scen["file"], triggered_by="api", **overrides)
    except Exception as exc:
        raise HTTPException(422, {"code": "invalid_config", "message": str(exc)[:500]}) from exc
    test_run_id = test_runner.manager.start(cfg)
    return {"test_run_id": test_run_id, "status": "queued", "status_url": f"/api/v1/test-runs/{test_run_id}",
            "config": cfg.model_dump(mode="json")}


@router.get("/test-runs")
def list_test_runs(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Test runs from the lakehouse (all, incl. CLI) merged with live API-run status from PostgreSQL."""
    lake = qs.sql_rows(f"""
        SELECT test_run_id, test_run_name, status, seed, requested_tasks, workers, time_mode, scenario_file,
               started_at, ended_at, total_runs, total_events, triggered_by
        FROM {T}.agent_test_runs ORDER BY started_at DESC LIMIT ?""", [limit])
    try:
        ops = {r["test_run_id"]: r for r in test_runner.list_records(limit)}
    except Exception:
        ops = {}
    merged = []
    for row in lake:
        live = ops.pop(row["test_run_id"], None)
        merged.append({**row, "source": "lakehouse", **({"api_status": live["status"], "progress_tasks": live["progress_tasks"]} if live else {})})
    for live in ops.values():  # API runs whose start event has not landed in the lakehouse yet
        merged.append({"test_run_id": live["test_run_id"], "test_run_name": live["name"], "status": live["status"],
                       "requested_tasks": live["requested_tasks"], "progress_tasks": live["progress_tasks"],
                       "started_at": live["created_at"], "source": "api", "api_status": live["status"]})
    merged.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return {"test_runs": merged[:limit], "active": test_runner.manager.active()}


@router.get("/test-runs/{test_run_id}")
def get_test_run(test_run_id: str = PathParam(..., pattern=TR_ID)) -> dict:
    lake = qs.sql_rows(f"SELECT * FROM {T}.agent_test_runs WHERE test_run_id = ?", [test_run_id])
    try:
        ops = test_runner.get_record(test_run_id)
    except Exception:
        ops = None
    if not lake and ops is None:
        raise HTTPException(404, {"code": "test_run_not_found", "message": test_run_id})
    p = [test_run_id]
    stats = qs.sql_rows(f"""
        SELECT count(*) AS runs_landed, avg(IF(task_success, 1e0, 0e0)) AS success_rate,
               approx_percentile(latency_ms, 0.5) AS p50_latency_ms, approx_percentile(latency_ms, 0.95) AS p95_latency_ms,
               sum(total_tokens) AS tokens, sum(estimated_cost_usd) AS est_cost_usd,
               count_if(status <> 'completed') AS failed_runs, min(event_time) AS first_event, max(event_time) AS last_event
        FROM {T}.agent_run_metrics WHERE test_run_id = ?""", p)[0]
    ingest = qs.sql_rows(f"""
        SELECT count(*) AS events_landed, count_if(NOT is_valid) AS invalid_events,
               min(ingested_at) AS first_ingested, max(ingested_at) AS last_ingested
        FROM {T}.raw_agent_events WHERE test_run_id = ?""", p)[0]
    by_agent = qs.sql_rows(f"""
        SELECT agent_id, agent_version, count(*) AS runs, avg(IF(task_success, 1e0, 0e0)) AS success_rate,
               approx_percentile(latency_ms, 0.95) AS p95_latency_ms
        FROM {T}.agent_run_metrics WHERE test_run_id = ? GROUP BY 1, 2 ORDER BY 1, 2""", p)
    findings = qs.sql_rows(f"""
        SELECT severity, count(*) AS n FROM {T}.agent_security_findings WHERE test_run_id = ? GROUP BY 1""", p)
    alerts = qs.sql_scalar(f"SELECT count(*) FROM {T}.agent_anomaly_alerts WHERE test_run_id = ?", p)
    gates = qs.sql_rows(f"""
        SELECT gate_id, agent_id, baseline_version, candidate_version, max(verdict) AS verdict, max(evaluated_at) AS evaluated_at
        FROM {T}.agent_regression_results WHERE test_run_id = ? GROUP BY 1, 2, 3, 4 ORDER BY evaluated_at DESC""", p)
    return {"test_run_id": test_run_id, "lakehouse": lake[0] if lake else None, "operational": ops,
            "stats": stats, "ingest": ingest, "by_agent": by_agent, "security_findings": findings,
            "anomaly_alerts": alerts, "regression_gates": gates}


@router.post("/test-runs/{test_run_id}/stop")
def stop_test_run(test_run_id: str = PathParam(..., pattern=TR_ID)) -> dict:
    stopped = test_runner.manager.stop(test_run_id)
    return {"test_run_id": test_run_id, "stop_signalled": stopped,
            "message": "workers will stop after their current task" if stopped else "run is not active in this API process"}


class GateRequest(BaseModel):
    agent_id: str = Field(pattern=r"^[a-z0-9\-]{3,64}$")
    baseline_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    candidate_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    scenario: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    test_run_id: str | None = Field(None, pattern=TR_ID)
    days: int = Field(30, ge=1, le=3650)


@router.post("/regression-gate")
def run_regression_gate(body: GateRequest) -> dict:
    """Compare candidate vs baseline cohorts against config/thresholds.yaml; result is stored in the lakehouse.
    The gate recommends - promotion decisions remain human-approved."""
    try:
        r = regression_gate.run_gate(body.agent_id, body.baseline_version, body.candidate_version, body.days,
                                     body.scenario, body.test_run_id)
    except Exception as exc:
        raise HTTPException(503, {"code": "gate_failed", "message": str(exc)[:500]}) from exc
    return r.to_dict()


@router.get("/regression-gate/results")
def gate_results(limit: int = Query(20, ge=1, le=200)) -> dict:
    rows = qs.sql_rows(f"""
        WITH latest AS (
            SELECT gate_id, max(evaluated_at) AS evaluated_at FROM {T}.agent_regression_results
            GROUP BY gate_id ORDER BY 2 DESC LIMIT ?)
        SELECT r.* FROM {T}.agent_regression_results r JOIN latest l ON l.gate_id = r.gate_id
        ORDER BY r.evaluated_at DESC, r.check_name""", [limit])
    gates: dict[str, dict] = {}
    for row in rows:
        g = gates.setdefault(row["gate_id"], {k: row[k] for k in (
            "gate_id", "evaluated_at", "agent_id", "baseline_version", "candidate_version", "scenario_id",
            "test_run_id", "verdict", "baseline_runs", "candidate_runs", "success_p_value")} | {"checks": []})
        g["checks"].append({k: row[k] for k in ("check_name", "unit", "baseline_value", "candidate_value", "delta",
                                                 "review_threshold", "fail_threshold", "check_status", "note")})
    return {"gates": list(gates.values())}
