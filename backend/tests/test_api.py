"""API behaviour tests. Lakehouse access is mocked, so these run without Docker."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import query_service as qs
from lakehouse.trino_client import QueryResult


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("backend.app.db.init_db", lambda: None)
    monkeypatch.setattr("backend.app.services.test_runner.manager.recover_orphans", lambda: 0)
    qs._cache.clear()
    return TestClient(app)


@pytest.fixture()
def captured(monkeypatch):
    """Capture SQL + parameters sent to Trino and return a canned result."""
    calls: list[tuple[str, list | None]] = []

    def fake_run_query(sql, params=None, max_rows=None, **kw):
        calls.append((sql, params))
        return QueryResult(columns=["a", "b"], rows=[[1, "x"]], elapsed_ms=1.0, query_id="q1", stats={"processedRows": 1})

    monkeypatch.setattr("backend.app.services.query_service.run_query", fake_run_query)
    return calls


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_sql_showcase_lists_read_only_catalog(client):
    r = client.get("/api/v1/analytics/sql-showcase")
    assert r.status_code == 200
    queries = r.json()["queries"]
    assert len(queries) >= 40
    assert all(q["sql"].lstrip().upper().startswith(("SELECT", "WITH", "EXPLAIN")) for q in queries)
    assert all(q["question"] and q["concept"] for q in queries)


def test_named_query_binds_parameters(client, captured):
    r = client.post("/api/v1/analytics/sql-showcase/rolling_success_rate/run", json={"days": 7, "agent_id": "rag-helpdesk"})
    assert r.status_code == 200
    sql, params = captured[-1]
    assert "rag-helpdesk" not in sql and params == [7, "rag-helpdesk"]
    assert r.json()["rows"] == [{"a": 1, "b": "x"}]


@pytest.mark.parametrize("body", [
    {"days": "7; DROP TABLE x"},
    {"days": -1},
    {"agent_id": "x' OR '1'='1"},
    {"unknown_param": 1},
])
def test_named_query_rejects_bad_parameters(client, captured, body):
    r = client.post("/api/v1/analytics/sql-showcase/rolling_success_rate/run", json=body)
    assert r.status_code == 422
    assert captured == []  # nothing reached Trino


def test_unknown_query_404(client, captured):
    assert client.post("/api/v1/analytics/sql-showcase/drop_everything/run", json={}).status_code == 404


def test_run_explorer_passes_filters_as_parameters(client, monkeypatch):
    seen = {}

    def fake_rows(sql, params=None, max_rows=None):
        seen["sql"], seen["params"] = sql, params
        return []

    monkeypatch.setattr("backend.app.services.query_service.sql_rows", fake_rows)
    r = client.get("/api/v1/runs", params={"agent_id": "qa-assistant", "status": "failed", "min_latency_ms": 500, "limit": 10})
    assert r.status_code == 200
    assert "qa-assistant" not in seen["sql"]
    assert seen["params"] == [30, "qa-assistant", "failed", 500.0, 0, 10]


@pytest.mark.parametrize("path", [
    "/api/v1/runs?agent_id=x%27%3B--",
    "/api/v1/runs?status=deleted",
    "/api/v1/traces/not-a-trace",
    "/api/v1/analytics/comparison?versions=a",
    "/api/v1/test-runs/TR-bad",
])
def test_input_validation_422(client, path):
    assert client.get(path).status_code == 422


def test_test_run_request_validation(client):
    r = client.post("/api/v1/test-runs", json={"scenario": "smoke", "fault_profile": {"rm_rf": 0.1}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert client.post("/api/v1/test-runs", json={"scenario": "smoke", "tasks": 10_000_000}).status_code == 422
    assert client.post("/api/v1/test-runs", json={"scenario": "../../etc/passwd"}).status_code == 422


def test_lakehouse_outage_is_503_not_500(client, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("trino down")

    monkeypatch.setattr("backend.app.services.query_service.run_query", boom)
    r = client.post("/api/v1/analytics/sql-showcase/error_categories/run", json={})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "lakehouse_query_failed"
