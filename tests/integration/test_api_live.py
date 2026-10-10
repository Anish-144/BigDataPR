"""Live API checks against the running stack (http://localhost:8000).

Run with:  pytest -m integration tests/integration/test_api_live.py
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration
BASE = "http://127.0.0.1:8000"


@pytest.fixture(scope="module")
def client():
    c = httpx.Client(base_url=BASE, timeout=120)
    try:
        c.get("/health").raise_for_status()
    except Exception:
        pytest.skip("API not reachable on localhost:8000 (docker compose up -d)")
    yield c
    c.close()


def test_pipeline_health_reports_measured_components(client):
    d = client.get("/api/v1/pipeline/health").json()
    for comp in ("kafka", "spark", "trino", "postgres"):
        assert d["components"][comp]["status"] in ("ok", "degraded"), (comp, d["components"][comp])
    tables = d["components"]["trino"]["lakehouse_tables"]
    assert tables["raw_agent_events"]["rows"] > 0 and tables["agent_spans"]["files"] > 0


def test_overview_matches_lakehouse(client):
    d = client.get("/api/v1/overview", params={"days": 30}).json()
    assert d["runs"]["total_runs"] > 0 and 0 <= d["runs"]["success_rate"] <= 1
    assert d["hourly_trend"]


def test_every_catalog_query_runs(client):
    queries = client.get("/api/v1/analytics/sql-showcase").json()["queries"]
    assert len(queries) >= 45
    failures = []
    for q in queries:
        if q["name"].startswith("layout_lookup"):
            continue  # needs a real trace id; covered by benchmarks/sql_benchmark.py
        r = client.post(f"/api/v1/analytics/sql-showcase/{q['name']}/run", json={})
        if r.status_code != 200:
            failures.append((q["name"], r.status_code, r.text[:200]))
    assert not failures, failures


def test_trace_detail_is_consistent(client):
    run = client.get("/api/v1/runs", params={"limit": 1, "status": "timeout"}).json()["rows"][0]
    t = client.get(f"/api/v1/traces/{run['trace_id']}").json()
    assert t["run"]["run_id"] == run["run_id"]
    assert sum(1 for s in t["spans"] if s["parent_span_id"] is None) == 1
    assert any(s["status"] == "timeout" for s in t["spans"])


@pytest.mark.parametrize("question,intent", [
    ("Why did run R-104 fail?", "run_diagnosis"),
    ("Compare rag-helpdesk 2.0.0 and 2.1.0 for latency, cost and task success.", "version_compare"),
    ("Show the main causes of timeouts during the last test.", "timeout_causes"),
    ("Why was this tool call flagged?", "flagged_explain"),
    ("What changed in the last regression run?", "regression_changes"),
    ("Suggest improvements for the highest-cost agent.", "cost_improvements"),
])
def test_investigation_spec_questions_are_grounded(client, question, intent):
    d = client.post("/api/v1/investigations", json={"question": question}).json()
    assert d["intent"] == intent and d["grounded"] and d["evidence"], d.get("answer", "")[:300]


def test_investigation_declines_without_evidence(client):
    d = client.post("/api/v1/investigations", json={"question": "What is the capital of Australia?"}).json()
    assert d["grounded"] is False and d["evidence"] == []


def test_regression_gate_endpoint_and_results(client):
    r = client.post("/api/v1/regression-gate", json={"agent_id": "rag-helpdesk", "baseline_version": "2.0.0",
                                                    "candidate_version": "2.1.0", "scenario": "regression"})
    assert r.status_code == 200
    g = r.json()
    assert g["verdict"] in ("PASSED", "NEEDS_REVIEW", "FAILED", "INSUFFICIENT_DATA")
    assert {c["name"] for c in g["checks"]} >= {"success_rate_drop", "p95_latency_increase", "retrieval_recall_drop"}
    stored = client.get("/api/v1/regression-gate/results", params={"limit": 50}).json()["gates"]
    assert any(s["gate_id"] == g["gate_id"] for s in stored)


def test_anomaly_summary_has_holdout_evaluation(client):
    d = client.get("/api/v1/anomalies/summary").json()
    assert d["detector_evaluation"]["eval_scenario"].endswith("holdout")
    assert d["by_detector_type_severity"]


def test_report_export_formats(client):
    tr = next(r["test_run_id"] for r in client.get("/api/v1/test-runs").json()["test_runs"] if (r.get("total_runs") or 0) > 1000)
    for fmt, ctype in (("json", "application/json"), ("csv", "text/csv"), ("md", "text/plain"), ("html", "text/html")):
        r = client.get(f"/api/v1/reports/{tr}", params={"format": fmt})
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)
