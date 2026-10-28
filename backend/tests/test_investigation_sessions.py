"""Tests for AI Assistant Multi-Turn Session Memory & Evaluation Store (MongoDB-backed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app import mongo
from backend.app.routers import investigations
from backend.app.services import query_service as qs
from investigation import answer_service as svc


@pytest.fixture()
def mock_sessions_collection(monkeypatch):
    """Provide an isolated in-memory mongomock collection for investigation_sessions."""
    client = mongomock.MongoClient()
    col = client["agentshield"]["investigation_sessions"]
    col.create_index("session_id", unique=True)
    monkeypatch.setattr(investigations, "get_sessions_collection", lambda: col)
    monkeypatch.setattr(mongo, "get_sessions_collection", lambda: col)
    return col


@pytest.fixture()
def mock_investigate(monkeypatch):
    """Mock the Lakehouse Trino-backed investigate call for hermetic testing."""
    def fake_investigate(question: str, context: svc.Context, use_llm: bool = True):
        return svc.Answer(
            question=question,
            intent="version_compare" if "compare" in question.lower() else "timeout_causes",
            answer=f"Simulated grounded answer for: {question}",
            evidence=[
                svc.Evidence(
                    kind="metric",
                    ref="lakehouse.analytics.hourly_agent_summary",
                    title="P95 Latency Aggregate",
                    detail="Aggregated from test cohorts",
                )
            ],
            grounded=True,
            suggested_questions=["Follow-up question 1?"],
            mode="deterministic",
        )

    monkeypatch.setattr(svc, "investigate", fake_investigate)
    monkeypatch.setattr(investigations.svc, "investigate", fake_investigate)
    return fake_investigate


@pytest.fixture()
def client(mock_sessions_collection, mock_investigate, monkeypatch):
    monkeypatch.setattr("backend.app.db.init_db", lambda: None)
    monkeypatch.setattr("backend.app.mongo.init_mongo", lambda: None)
    monkeypatch.setattr("backend.app.services.test_runner.manager.recover_orphans", lambda: 0)
    qs._cache.clear()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Infrastructure & Schema Tests
# ---------------------------------------------------------------------------


def test_sessions_collection_name():
    col = mongo.get_sessions_collection()
    assert col.name == "investigation_sessions"


def test_sessions_schema_definition():
    schema = mongo.SESSIONS_SCHEMA
    assert "$jsonSchema" in schema
    js = schema["$jsonSchema"]
    assert js["bsonType"] == "object"
    assert "session_id" in js["required"]
    assert "title" in js["required"]
    assert "status" in js["required"]
    assert "turn_count" in js["required"]
    assert set(js["properties"]["status"]["enum"]) == {"ACTIVE", "ARCHIVED", "CLOSED"}


def test_sessions_indexes_specification():
    indexes = mongo.SESSIONS_INDEXES
    assert len(indexes) >= 8

    # Unique session_id index
    sess_id_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_session_id_unique"), None)
    assert sess_id_idx is not None
    assert sess_id_idx.document.get("unique") is True

    # Status & updated compound index
    status_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_sessions_status_updated"), None)
    assert status_idx is not None

    # Multikey evidence ref index
    evidence_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_multikey_turns_evidence_ref"), None)
    assert evidence_idx is not None

    # Text search index
    text_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_text_session_content"), None)
    assert text_idx is not None


# ---------------------------------------------------------------------------
# API Session Management & Conversation Turns Tests
# ---------------------------------------------------------------------------


def test_create_session_empty(client):
    body = {
        "title": "Investigation on rag-helpdesk",
        "analyst": "sarah.chen",
        "scope_context": {
            "agent_id": "rag-helpdesk",
            "agent_version": "2.1.0",
        },
        "tags": ["latency", "rag"],
    }
    r = client.post("/api/v1/investigations/sessions", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["session_id"].startswith("SESS-")
    assert data["title"] == body["title"]
    assert data["analyst"] == "sarah.chen"
    assert data["status"] == "ACTIVE"
    assert data["turn_count"] == 0
    assert data["turns"] == []
    assert data["scope_context"]["agent_id"] == "rag-helpdesk"


def test_create_session_with_initial_question(client):
    body = {
        "title": "Initial Question Session",
        "analyst": "alex.kumar",
        "initial_question": "Why did run R-104 fail?",
        "scope_context": {
            "run_id": "R-104000-000001",
        },
    }
    r = client.post("/api/v1/investigations/sessions", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["turn_count"] == 1
    assert len(data["turns"]) == 1
    t = data["turns"][0]
    assert t["turn_id"] == 1
    assert t["question"] == body["initial_question"]
    assert "Simulated grounded answer" in t["answer"]
    assert t["feedback"] is None


def test_add_turns_multi_turn_flow(client):
    # 1. Create session
    r1 = client.post(
        "/api/v1/investigations/sessions",
        json={"title": "Multi-Turn Investigation", "analyst": "lead_analyst"},
    )
    assert r1.status_code == 201
    session_id = r1.json()["session_id"]

    # 2. Add Turn 1
    r2 = client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "Compare rag-helpdesk 2.0.0 and 2.1.0 for latency"},
    )
    assert r2.status_code == 201
    t1 = r2.json()
    assert t1["session_id"] == session_id
    assert t1["turn"]["turn_id"] == 1
    assert t1["turn_count"] == 1

    # 3. Add Turn 2 (Follow-up)
    r3 = client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "Show the main causes of timeouts during the last test."},
    )
    assert r3.status_code == 201
    t2 = r3.json()
    assert t2["turn"]["turn_id"] == 2
    assert t2["turn_count"] == 2

    # 4. Retrieve complete session and verify turns order
    r4 = client.get(f"/api/v1/investigations/sessions/{session_id}")
    assert r4.status_code == 200
    sess = r4.json()
    assert sess["turn_count"] == 2
    assert len(sess["turns"]) == 2
    assert sess["turns"][0]["turn_id"] == 1
    assert sess["turns"][1]["turn_id"] == 2


def test_submit_turn_feedback_array_filters(client):
    # 1. Create session with 2 turns
    r1 = client.post(
        "/api/v1/investigations/sessions",
        json={"title": "Feedback Test Session"},
    )
    session_id = r1.json()["session_id"]

    client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "Why did run R-104 fail?"},
    )
    client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "What changed in the last regression run?"},
    )

    # 2. Submit feedback for Turn 2 using arrayFilters
    fb_body = {
        "rating": 5,
        "verdict": "accurate",
        "notes": "Verified numbers match Trino lakehouse directly.",
        "submitted_by": "qa_reviewer",
    }
    r_fb = client.patch(
        f"/api/v1/investigations/sessions/{session_id}/turns/2/feedback",
        json=fb_body,
    )
    assert r_fb.status_code == 200
    fb_data = r_fb.json()
    assert fb_data["session_id"] == session_id
    assert fb_data["turn_id"] == 2
    assert fb_data["feedback"]["rating"] == 5
    assert fb_data["feedback"]["verdict"] == "accurate"
    assert fb_data["feedback"]["submitted_by"] == "qa_reviewer"

    # 3. Verify Turn 1 feedback is still None while Turn 2 is updated
    sess = client.get(f"/api/v1/investigations/sessions/{session_id}").json()
    assert sess["turns"][0]["feedback"] is None
    assert sess["turns"][1]["feedback"]["rating"] == 5


def test_feedback_validation_errors(client):
    r1 = client.post(
        "/api/v1/investigations/sessions",
        json={"title": "Validation Error Session"},
    )
    session_id = r1.json()["session_id"]
    client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "Show timeouts"},
    )

    # Invalid rating (> 5)
    r_bad_rating = client.patch(
        f"/api/v1/investigations/sessions/{session_id}/turns/1/feedback",
        json={"rating": 6, "verdict": "accurate"},
    )
    assert r_bad_rating.status_code == 422

    # Invalid verdict
    r_bad_verdict = client.patch(
        f"/api/v1/investigations/sessions/{session_id}/turns/1/feedback",
        json={"rating": 4, "verdict": "nonsense"},
    )
    assert r_bad_verdict.status_code == 422


def test_list_and_filter_sessions(client):
    # Create two sessions
    client.post(
        "/api/v1/investigations/sessions",
        json={
            "title": "Session One",
            "analyst": "sarah.chen",
            "scope_context": {"agent_id": "qa-assistant"},
        },
    )
    client.post(
        "/api/v1/investigations/sessions",
        json={
            "title": "Session Two",
            "analyst": "alex.kumar",
            "scope_context": {"agent_id": "rag-helpdesk"},
        },
    )

    # List all
    r_all = client.get("/api/v1/investigations/sessions")
    assert r_all.status_code == 200
    assert r_all.json()["total"] >= 2

    # Filter by analyst
    r_sarah = client.get("/api/v1/investigations/sessions?analyst=sarah.chen")
    assert r_sarah.status_code == 200
    assert r_sarah.json()["total"] >= 1
    assert all(s["analyst"] == "sarah.chen" for s in r_sarah.json()["rows"])


def test_session_analytics_aggregation(client):
    # Create a session with turn and feedback
    r = client.post(
        "/api/v1/investigations/sessions",
        json={"title": "Analytics Test Session"},
    )
    session_id = r.json()["session_id"]
    client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "Show timeouts"},
    )
    client.patch(
        f"/api/v1/investigations/sessions/{session_id}/turns/1/feedback",
        json={"rating": 5, "verdict": "accurate"},
    )

    # Run analytics
    r_analytics = client.get("/api/v1/investigations/sessions/summary/analytics")
    assert r_analytics.status_code == 200
    data = r_analytics.json()
    assert "total_sessions" in data
    assert "status_breakdown" in data
    assert "avg_rating" in data
    assert "ratings_count" in data


def test_update_and_delete_session(client):
    r1 = client.post(
        "/api/v1/investigations/sessions",
        json={"title": "To Be Archived"},
    )
    session_id = r1.json()["session_id"]

    # Archive session
    r_patch = client.patch(
        f"/api/v1/investigations/sessions/{session_id}",
        json={"status": "ARCHIVED", "title": "Archived Session Title"},
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["status"] == "ARCHIVED"
    assert r_patch.json()["title"] == "Archived Session Title"

    # Cannot add turn to archived session
    r_bad_add = client.post(
        f"/api/v1/investigations/sessions/{session_id}/turns",
        json={"question": "Will fail"},
    )
    assert r_bad_add.status_code == 400

    # Delete session
    r_del = client.delete(f"/api/v1/investigations/sessions/{session_id}")
    assert r_del.status_code == 200
    assert r_del.json()["deleted"] is True

    # 404 after delete
    assert client.get(f"/api/v1/investigations/sessions/{session_id}").status_code == 404
