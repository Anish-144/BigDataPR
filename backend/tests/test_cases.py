"""Tests for Phase 2: Security Case Management REST API (MongoDB-backed)."""

from __future__ import annotations

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import PyMongoError

from backend.app.main import app
from backend.app.routers import cases
from backend.app.services import query_service as qs


@pytest.fixture()
def mock_mongo_collection(monkeypatch):
    """Provide an isolated in-memory mongomock collection for each test."""
    client = mongomock.MongoClient()
    col = client["agentshield"]["security_cases"]
    col.create_index("case_id", unique=True)
    monkeypatch.setattr(cases, "get_cases_collection", lambda: col)
    return col


@pytest.fixture()
def client(mock_mongo_collection, monkeypatch):
    monkeypatch.setattr("backend.app.db.init_db", lambda: None)
    monkeypatch.setattr("backend.app.mongo.init_mongo", lambda: None)
    monkeypatch.setattr("backend.app.services.test_runner.manager.recover_orphans", lambda: 0)
    qs._cache.clear()
    return TestClient(app)


def test_create_case_minimal(client):
    body = {
        "title": "Suspected prompt injection on QA Assistant",
        "severity": "high",
        "priority": "P1",
        "target_agent": {
            "agent_id": "qa-assistant",
            "agent_version": "1.1.0",
            "workload_type": "qa",
        },
        "created_by": "secops_lead",
    }
    r = client.post("/api/v1/cases", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == body["title"]
    assert data["status"] == "OPEN"
    assert data["severity"] == "high"
    assert data["priority"] == "P1"
    assert data["case_id"].startswith("CASE-")
    assert data["target_agent"]["agent_id"] == "qa-assistant"
    assert len(data["timeline"]) == 1
    assert data["timeline"][0]["action"] == "CASE_CREATED"
    assert data["timeline"][0]["author"] == "secops_lead"


def test_create_case_full_fields(client):
    body = {
        "case_id": "CASE-202610-0042",
        "title": "Exfiltration Sequence Detected",
        "severity": "critical",
        "priority": "P1",
        "target_agent": {
            "agent_id": "ops-tool-agent",
            "agent_version": "1.1.0",
            "workload_type": "tool",
            "model_name": "mock-small",
        },
        "assigned_analyst": {
            "username": "sarah.chen",
            "email": "schen@agentshield.internal",
        },
        "linked_findings": [
            {
                "finding_id": "SEC-F-8812",
                "rule_id": "SEC-003",
                "rule_name": "restricted_data_access",
                "severity": "high",
                "trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819",
                "span_id": "7f3a9c1e2b4d5a6b",
            }
        ],
        "linked_anomaly_alerts": [
            {
                "alert_id": "A-7f3a9c1e2b4d5a6b",
                "anomaly_type": "suspected_loop",
                "score": 0.942,
                "detector": "rules:timeout_loop",
            }
        ],
        "evidence_bundle": [
            {
                "evidence_id": "EV-01",
                "kind": "canary_leak",
                "title": "Canary Secret Detected",
                "detail": "Outbound HTTP egress attempted with canary AGSH-CANARY-5F1E9A3B",
            }
        ],
        "remediation": {
            "recommended_action": "REVOKE_TOOL",
            "policy_file": "config/policies.yaml",
            "target_tool": "curl_egress",
            "requires_code_freeze": True,
            "completed": False,
        },
        "tags": ["exfiltration", "canary_leak"],
        "initial_notes": "High confidence exfiltration pattern identified.",
    }
    r = client.post("/api/v1/cases", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["case_id"] == "CASE-202610-0042"
    assert len(data["linked_findings"]) == 1
    assert data["linked_findings"][0]["finding_id"] == "SEC-F-8812"
    assert len(data["evidence_bundle"]) == 1
    assert data["evidence_bundle"][0]["evidence_id"] == "EV-01"
    assert data["remediation"]["target_tool"] == "curl_egress"
    assert data["assigned_analyst"]["username"] == "sarah.chen"


def test_create_case_duplicate_id_conflict(client):
    body = {
        "case_id": "CASE-202610-0099",
        "title": "Duplicate ID test",
        "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"},
    }
    r1 = client.post("/api/v1/cases", json=body)
    assert r1.status_code == 201

    r2 = client.post("/api/v1/cases", json=body)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "case_exists"


def test_create_case_validation_errors(client):
    # Invalid case_id regex
    r = client.post("/api/v1/cases", json={"case_id": "invalid-id", "title": "Test", "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"}})
    assert r.status_code == 422

    # Title too short
    r = client.post("/api/v1/cases", json={"title": "x", "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"}})
    assert r.status_code == 422

    # Missing target_agent
    r = client.post("/api/v1/cases", json={"title": "Missing target agent"})
    assert r.status_code == 422


def test_list_and_filter_cases(client):
    # Seed 3 cases
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0001",
        "title": "Case 1",
        "severity": "critical",
        "priority": "P1",
        "target_agent": {"agent_id": "ops-tool-agent", "agent_version": "1.1.0"},
    })
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0002",
        "title": "Case 2",
        "severity": "low",
        "priority": "P3",
        "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"},
    })
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0003",
        "title": "Case 3",
        "severity": "critical",
        "priority": "P2",
        "target_agent": {"agent_id": "ops-tool-agent", "agent_version": "1.0.0"},
    })

    # Filter by severity
    r = client.get("/api/v1/cases", params={"severity": "critical"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert all(row["severity"] == "critical" for row in data["rows"])

    # Filter by agent_id
    r = client.get("/api/v1/cases", params={"agent_id": "qa-assistant"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["rows"][0]["case_id"] == "CASE-202610-0002"

    # Pagination
    r = client.get("/api/v1/cases", params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 2
    assert r.json()["has_more"] is True


def test_get_case_by_id(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0050",
        "title": "Detailed case test",
        "severity": "high",
        "target_agent": {"agent_id": "rag-helpdesk", "agent_version": "2.0.0"},
    })

    # Found
    r = client.get("/api/v1/cases/CASE-202610-0050")
    assert r.status_code == 200
    assert r.json()["case_id"] == "CASE-202610-0050"
    assert r.json()["title"] == "Detailed case test"

    # Not found
    r = client.get("/api/v1/cases/CASE-202610-9999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "case_not_found"


def test_patch_case_status_and_analyst_assignment(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0060",
        "title": "Lifecycle transition test",
        "severity": "medium",
        "target_agent": {"agent_id": "planner-agent", "agent_version": "1.0.0"},
    })

    # Transition status to IN_REVIEW and assign analyst
    patch_body = {
        "status": "IN_REVIEW",
        "assigned_analyst": {"username": "david.ross", "email": "dross@agentshield.internal"},
        "updated_by": "lead_analyst",
        "notes": "Assigning for deep packet inspection.",
    }
    r = client.patch("/api/v1/cases/CASE-202610-0060", json=patch_body)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "IN_REVIEW"
    assert data["assigned_analyst"]["username"] == "david.ross"

    # Verify timeline recorded audit entries
    timeline = data["timeline"]
    assert len(timeline) >= 2
    actions = [t["action"] for t in timeline]
    assert "STATUS_CHANGE_IN_REVIEW" in actions
    assert "ANALYST_ASSIGNED" in actions


def test_patch_case_remediation_completed(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0070",
        "title": "Remediation test",
        "severity": "high",
        "target_agent": {"agent_id": "ops-tool-agent", "agent_version": "1.1.0"},
        "remediation": {"recommended_action": "DROP_TOOL_PERMISSIONS", "target_tool": "shell_exec", "completed": False},
    })

    patch_body = {
        "status": "RESOLVED",
        "remediation": {"recommended_action": "DROP_TOOL_PERMISSIONS", "target_tool": "shell_exec", "completed": True},
        "updated_by": "sarah.chen",
        "notes": "Policy updated and verified.",
    }
    r = client.patch("/api/v1/cases/CASE-202610-0070", json=patch_body)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "RESOLVED"
    assert data["remediation"]["completed"] is True
    assert data["remediation"]["completed_by"] == "sarah.chen"
    assert data["remediation"]["completed_at"] is not None


def test_add_timeline_note_atomic_push(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0080",
        "title": "Timeline note test",
        "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"},
    })

    note_body = {
        "action": "FORENSIC_ANALYSIS",
        "notes": "Inspected trace waterfall. Third tool retry had 504 gateway timeout.",
        "author": "analyst_sam",
    }
    r = client.post("/api/v1/cases/CASE-202610-0080/timeline", json=note_body)
    assert r.status_code == 201
    entry = r.json()["timeline_entry"]
    assert entry["action"] == "FORENSIC_ANALYSIS"
    assert entry["author"] == "analyst_sam"
    assert "504 gateway timeout" in entry["notes"]

    # Verify document now has 2 timeline items
    c = client.get("/api/v1/cases/CASE-202610-0080").json()
    assert len(c["timeline"]) == 2


def test_link_finding_to_case_idempotent(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0090",
        "title": "Link finding test",
        "target_agent": {"agent_id": "ops-tool-agent", "agent_version": "1.0.0"},
    })

    finding_body = {
        "finding_id": "SEC-F-9901",
        "rule_id": "SEC-001",
        "rule_name": "tool_allowlist_violation",
        "severity": "medium",
        "trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819",
        "span_id": "1122334455667788",
    }
    # Link finding first time
    r1 = client.post("/api/v1/cases/CASE-202610-0090/findings", json=finding_body)
    assert r1.status_code == 200
    assert len(r1.json()["linked_findings"]) == 1

    # Link same finding second time (idempotent, no duplicates)
    r2 = client.post("/api/v1/cases/CASE-202610-0090/findings", json=finding_body)
    assert r2.status_code == 200
    assert r2.json()["message"] == "Finding already linked"


def test_add_evidence_item(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0100",
        "title": "Evidence attachment test",
        "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"},
    })

    ev_body = {
        "kind": "canary_leak",
        "title": "Canary token in egress buffer",
        "detail": "AGSH-CANARY-5F1E9A3B present in serialized payload preview",
        "ref": "span:7f3a9c",
    }
    r = client.post("/api/v1/cases/CASE-202610-0100/evidence", json=ev_body)
    assert r.status_code == 201
    assert r.json()["evidence_id"].startswith("EV-")
    assert r.json()["evidence_item"]["title"] == ev_body["title"]


def test_escalate_finding_from_lakehouse(client, monkeypatch):
    # Mock lakehouse query service to return synthetic finding
    def fake_sql_rows(sql, params):
        assert params == ["SEC-F-5555"]
        return [{
            "finding_id": "SEC-F-5555",
            "rule_id": "SEC-007",
            "rule_name": "exfiltration_sequence",
            "category": "exfiltration",
            "severity": "critical",
            "agent_id": "ops-tool-agent",
            "agent_version": "1.1.0",
            "test_run_id": "TR-20261009-7f3a9c",
            "run_id": "R-7f3a9c-000104",
            "trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819",
            "span_id": "7f3a9c1e2b4d5a6b",
            "tool_name": "curl_egress",
            "action": "blocked",
            "detector": "heuristic_sequence_detector",
            "evidence": "Restricted file read followed by blocked egress.",
            "event_time": "2026-10-09T14:22:28Z",
        }]

    monkeypatch.setattr(qs, "sql_rows", fake_sql_rows)

    r = client.post("/api/v1/cases/escalate-finding", json={
        "finding_id": "SEC-F-5555",
        "priority": "P1",
        "created_by": "triage_bot",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["severity"] == "critical"
    assert data["priority"] == "P1"
    assert "exfiltration_sequence" in data["title"]
    assert len(data["linked_findings"]) == 1
    assert data["linked_findings"][0]["finding_id"] == "SEC-F-5555"
    assert len(data["evidence_bundle"]) == 1


def test_escalate_finding_not_found(client, monkeypatch):
    monkeypatch.setattr(qs, "sql_rows", lambda sql, params: [])
    r = client.post("/api/v1/cases/escalate-finding", json={"finding_id": "SEC-F-NONE"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "finding_not_found"


def test_case_analytics_aggregations(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0110",
        "title": "Analytics case 1",
        "severity": "critical",
        "priority": "P1",
        "target_agent": {"agent_id": "ops-tool-agent", "agent_version": "1.1.0"},
        "linked_findings": [
            {"finding_id": "SEC-F-01", "rule_id": "SEC-007", "rule_name": "exfiltration", "severity": "critical", "trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819"}
        ],
    })
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0120",
        "title": "Analytics case 2",
        "severity": "high",
        "priority": "P2",
        "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"},
        "linked_findings": [
            {"finding_id": "SEC-F-02", "rule_id": "SEC-001", "rule_name": "allowlist", "severity": "medium", "trace_id": "0192a7f3b89c71e2a0b3c4d5e6f70819"}
        ],
    })

    r = client.get("/api/v1/cases/summary/analytics")
    assert r.status_code == 200
    data = r.json()
    assert data["total_open_cases"] == 2
    assert data["severity_breakdown"]["critical"] == 1
    assert data["severity_breakdown"]["high"] == 1
    assert len(data["by_agent"]) == 2
    assert len(data["top_breached_rules"]) >= 1


def test_delete_case(client):
    client.post("/api/v1/cases", json={
        "case_id": "CASE-202610-0130",
        "title": "Delete test",
        "target_agent": {"agent_id": "qa-assistant", "agent_version": "1.0.0"},
    })

    r = client.delete("/api/v1/cases/CASE-202610-0130")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    # Confirm it is gone
    r2 = client.get("/api/v1/cases/CASE-202610-0130")
    assert r2.status_code == 404


def test_mongo_outage_returns_503(client, monkeypatch):
    def boom():
        raise PyMongoError("Connection refused")

    monkeypatch.setattr(cases, "get_cases_collection", boom)
    r = client.get("/api/v1/cases")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "case_store_unavailable"
