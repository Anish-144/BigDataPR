"""Tests for Phase 1 MongoDB infrastructure, connection lifecycle, and schema definitions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pymongo import ASCENDING, DESCENDING, TEXT, MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from backend.app import mongo
from common.settings import get_settings


def test_mongo_settings():
    s = get_settings()
    assert s.mongo_uri.startswith("mongodb://")
    assert s.mongo_db == "agentshield"


def test_mongo_client_configuration():
    mongo.close_mongo_client()
    client = mongo.get_mongo_client()
    assert isinstance(client, MongoClient)
    # Validate connection pool and timeout settings
    opts = client.options
    assert opts.pool_options.max_pool_size == 10
    assert opts.pool_options.min_pool_size == 1
    assert opts.server_selection_timeout == 2.0
    assert opts.pool_options.connect_timeout == 2.0
    assert opts.pool_options.socket_timeout == 5.0
    mongo.close_mongo_client()


def test_cases_collection_name():
    col = mongo.get_cases_collection()
    assert col.name == "security_cases"
    assert col.database.name == get_settings().mongo_db


def test_cases_schema_definition():
    schema = mongo.CASES_SCHEMA
    assert "$jsonSchema" in schema
    js = schema["$jsonSchema"]
    assert js["bsonType"] == "object"
    assert "case_id" in js["required"]
    assert "title" in js["required"]
    assert "status" in js["required"]
    assert "severity" in js["required"]
    assert "target_agent" in js["required"]
    assert "created_at" in js["required"]

    # Verify status enum includes operational lifecycle states
    status_enum = js["properties"]["status"]["enum"]
    for expected in ["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING", "RESOLVED", "DISMISSED"]:
        assert expected in status_enum

    # Verify severity enum
    assert set(js["properties"]["severity"]["enum"]) == {"low", "medium", "high", "critical"}


def test_cases_indexes_specification():
    indexes = mongo.CASES_INDEXES
    assert len(indexes) >= 7

    # Find unique case_id index
    case_id_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_case_id_unique"), None)
    assert case_id_idx is not None
    assert case_id_idx.document.get("unique") is True

    # Find triage SLA compound index
    triage_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_cases_triage_sla"), None)
    assert triage_idx is not None
    keys = list(triage_idx.document["key"].items())
    assert keys == [("status", ASCENDING), ("severity", ASCENDING), ("priority", ASCENDING), ("created_at", DESCENDING)]

    # Find multikey trace index
    trace_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_multikey_findings_trace_id"), None)
    assert trace_idx is not None

    # Find text search index
    text_idx = next((idx for idx in indexes if idx.document.get("name") == "idx_text_title_notes"), None)
    assert text_idx is not None
    assert text_idx.document["key"]["title"] == "text"


def test_mongo_health_check_down_graceful():
    # When MongoDB is unreachable, check_mongo_health must return status: down without throwing
    with patch.object(mongo, "get_mongo_client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.admin.command.side_effect = ServerSelectionTimeoutError("connection timed out")
        mock_client.return_value = mock_instance

        res = mongo.check_mongo_health()
        assert res["status"] == "down"
        assert "ServerSelectionTimeoutError" in res["error"]
        assert "latency_ms" in res


def test_mongo_health_check_ok():
    with patch.object(mongo, "get_mongo_client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.admin.command.return_value = {"ok": 1}
        mock_db = MagicMock()
        mock_db.name = "agentshield"
        mock_db.list_collection_names.return_value = ["security_cases"]
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 42
        mock_db.__getitem__.return_value = mock_col
        mock_instance.__getitem__.return_value = mock_db
        mock_client.return_value = mock_instance

        res = mongo.check_mongo_health()
        assert res["status"] == "ok"
        assert res["database"] == "agentshield"
        assert "security_cases" in res["collections"]
        assert res["cases_count"] == 42


def test_init_mongo_degrades_gracefully_on_outage():
    # init_mongo must catch connection failures and log a warning without crashing
    with patch.object(mongo, "get_mongo_client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.admin.command.side_effect = ConnectionFailure("could not reach mongo")
        mock_client.return_value = mock_instance

        # Must not raise
        mongo.init_mongo()
