"""MongoDB client lifecycle, connection pooling, collection indexing, and schema validation.

Analytical facts remain in the Iceberg/Trino lakehouse; MongoDB serves as the
operational store for mutable security investigation cases, collaborative analyst
timelines, polymorphic evidence attachments, and remediation tracking.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from common.settings import get_settings

log = logging.getLogger("agentshield.mongo")

CASES_COLLECTION = "security_cases"

CASES_SCHEMA: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["case_id", "title", "status", "severity", "target_agent", "created_at"],
        "properties": {
            "case_id": {
                "bsonType": "string",
                "pattern": r"^CASE-[0-9]{6}-[0-9a-fA-F]{4,8}$",
                "description": "Standardized unique case identifier, e.g. CASE-202610-0042",
            },
            "title": {
                "bsonType": "string",
                "minLength": 3,
                "maxLength": 256,
                "description": "Descriptive human-readable case title",
            },
            "status": {
                "enum": ["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING", "RESOLVED", "DISMISSED"],
                "description": "Operational incident state",
            },
            "severity": {
                "enum": ["low", "medium", "high", "critical"],
                "description": "Case severity level",
            },
            "priority": {
                "enum": ["P1", "P2", "P3", "P4"],
                "description": "Operational response priority",
            },
            "assigned_analyst": {
                "bsonType": ["object", "null"],
                "properties": {
                    "username": {"bsonType": "string"},
                    "email": {"bsonType": "string"},
                    "assigned_at": {"bsonType": "date"},
                },
            },
            "target_agent": {
                "bsonType": "object",
                "required": ["agent_id", "agent_version"],
                "properties": {
                    "agent_id": {"bsonType": "string"},
                    "agent_version": {"bsonType": "string"},
                    "workload_type": {"bsonType": "string"},
                    "model_name": {"bsonType": "string"},
                },
            },
            "linked_findings": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["finding_id", "rule_id", "trace_id"],
                    "properties": {
                        "finding_id": {"bsonType": "string"},
                        "rule_id": {"bsonType": "string"},
                        "rule_name": {"bsonType": "string"},
                        "severity": {"bsonType": "string"},
                        "trace_id": {"bsonType": "string"},
                        "span_id": {"bsonType": ["string", "null"]},
                        "event_time": {"bsonType": ["date", "string"]},
                    },
                },
            },
            "linked_anomaly_alerts": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["alert_id", "anomaly_type"],
                    "properties": {
                        "alert_id": {"bsonType": "string"},
                        "anomaly_type": {"bsonType": "string"},
                        "score": {"bsonType": "double"},
                        "detector": {"bsonType": "string"},
                    },
                },
            },
            "evidence_bundle": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["evidence_id", "kind"],
                    "properties": {
                        "evidence_id": {"bsonType": "string"},
                        "kind": {"bsonType": "string"},
                        "title": {"bsonType": "string"},
                        "detail": {"bsonType": "string"},
                        "ref": {"bsonType": "string"},
                        "metadata": {"bsonType": "object"},
                    },
                },
            },
            "timeline": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["timestamp", "author", "action", "notes"],
                    "properties": {
                        "timestamp": {"bsonType": "date"},
                        "author": {"bsonType": "string"},
                        "action": {"bsonType": "string"},
                        "notes": {"bsonType": "string"},
                    },
                },
            },
            "remediation": {
                "bsonType": ["object", "null"],
                "properties": {
                    "recommended_action": {"bsonType": "string"},
                    "policy_file": {"bsonType": "string"},
                    "target_tool": {"bsonType": "string"},
                    "requires_code_freeze": {"bsonType": "bool"},
                    "completed": {"bsonType": "bool"},
                    "completed_at": {"bsonType": ["date", "null"]},
                    "completed_by": {"bsonType": ["string", "null"]},
                },
            },
            "tags": {
                "bsonType": "array",
                "items": {"bsonType": "string"},
            },
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}

CASES_INDEXES: list[IndexModel] = [
    IndexModel([("case_id", ASCENDING)], unique=True, name="idx_case_id_unique"),
    IndexModel(
        [("status", ASCENDING), ("severity", ASCENDING), ("priority", ASCENDING), ("created_at", DESCENDING)],
        name="idx_cases_triage_sla",
    ),
    IndexModel(
        [("target_agent.agent_id", ASCENDING), ("target_agent.agent_version", ASCENDING)],
        name="idx_cases_target_agent",
    ),
    IndexModel([("linked_findings.finding_id", ASCENDING)], name="idx_multikey_findings_finding_id"),
    IndexModel([("linked_findings.trace_id", ASCENDING)], name="idx_multikey_findings_trace_id"),
    IndexModel([("linked_anomaly_alerts.alert_id", ASCENDING)], name="idx_multikey_alerts_alert_id"),
    IndexModel([("title", TEXT), ("timeline.notes", TEXT)], name="idx_text_title_notes"),
]


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    """Return a thread-safe MongoClient with bounded connection pool and fast timeouts."""
    settings = get_settings()
    return MongoClient(
        settings.mongo_uri,
        maxPoolSize=10,
        minPoolSize=1,
        serverSelectionTimeoutMS=2000,
        connectTimeoutMS=2000,
        socketTimeoutMS=5000,
        retryWrites=True,
    )


def close_mongo_client() -> None:
    """Close the cached client and clear the cache (useful for test isolation)."""
    try:
        client = get_mongo_client()
        client.close()
    except Exception:
        pass
    get_mongo_client.cache_clear()


def get_mongo_db(db_name: str | None = None) -> Database:
    """Return the AgentShield MongoDB database instance."""
    name = db_name or get_settings().mongo_db
    return get_mongo_client()[name]


def get_cases_collection() -> Collection:
    """Return the security_cases collection."""
    return get_mongo_db()[CASES_COLLECTION]


def init_mongo() -> None:
    """Idempotently initialize MongoDB collection, schema validation, and indexes.

    Degrades gracefully: if MongoDB is offline or unreachable at startup, logs
    an error without crashing the application process.
    """
    try:
        client = get_mongo_client()
        # Fast ping to verify connectivity
        client.admin.command("ping")
        db = get_mongo_db()

        existing = db.list_collection_names()
        if CASES_COLLECTION not in existing:
            db.create_collection(CASES_COLLECTION, validator=CASES_SCHEMA)
            log.info("created MongoDB collection '%s' with $jsonSchema validation", CASES_COLLECTION)
        else:
            try:
                db.command("collMod", CASES_COLLECTION, validator=CASES_SCHEMA)
            except Exception as exc:
                log.warning("could not update validator on collection '%s': %s", CASES_COLLECTION, exc)

        col = db[CASES_COLLECTION]
        col.create_indexes(CASES_INDEXES)
        log.info("verified %d indexes on collection '%s'", len(CASES_INDEXES), CASES_COLLECTION)
    except (PyMongoError, ServerSelectionTimeoutError, Exception) as exc:
        log.warning("MongoDB unavailable during init_mongo (operating in degraded mode): %s", exc)


def check_mongo_health() -> dict[str, Any]:
    """Measure MongoDB connectivity, latency, and database status."""
    t0 = time.perf_counter()
    try:
        client = get_mongo_client()
        client.admin.command("ping")
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        db = get_mongo_db()
        cols = db.list_collection_names()
        cases_count = db[CASES_COLLECTION].count_documents({}) if CASES_COLLECTION in cols else 0

        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "database": db.name,
            "collections": sorted(cols),
            "cases_count": cases_count,
        }
    except Exception as exc:
        return {
            "status": "down",
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
