"""AgentShield — Safe PostgreSQL to MongoDB Migration Script.

Migrates legacy single-turn investigation records from the PostgreSQL
`investigations` table into the MongoDB `investigation_sessions` collection.

Guarantees:
- Read-only on PostgreSQL (preserves all existing relational rows).
- Idempotent on MongoDB (checks existing `session_id` before inserting).
- Maps each legacy investigation into a valid MongoDB session document
  with Turn 1 populated, schema-compliant BSON types, and ISO timestamps.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app import db  # noqa: E402
from app.mongo import (  # noqa: E402
    MONGO_DB_NAME,
    MONGO_URI,
    SESSIONS_COLLECTION,
    init_mongo,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate_investigations")


def migrate(dry_run: bool = False, limit: int | None = None) -> dict[str, int]:
    """Execute migration from PostgreSQL `investigations` to MongoDB `investigation_sessions`."""
    log.info("Starting safe migration (dry_run=%s, limit=%s)...", dry_run, limit)

    # 1. Initialize MongoDB collection & indexes
    if not dry_run:
        try:
            init_mongo()
        except Exception as exc:
            log.warning("Could not run full init_mongo (continuing): %s", exc)

    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_db = mongo_client[MONGO_DB_NAME]
    sessions_col = mongo_db[SESSIONS_COLLECTION]

    # 2. Query PostgreSQL legacy logs
    engine = db.engine
    with Session(engine) as session:
        stmt = select(db.InvestigationLog).order_by(db.InvestigationLog.id.asc())
        if limit:
            stmt = stmt.limit(limit)
        legacy_rows = session.scalars(stmt).all()

    total_legacy = len(legacy_rows)
    log.info("Found %d legacy investigation records in PostgreSQL.", total_legacy)

    migrated_count = 0
    skipped_count = 0
    error_count = 0

    now_utc = datetime.now(timezone.utc)

    for row in legacy_rows:
        # Formulate stable deterministic session ID based on legacy PK
        session_id = f"SES-MIG-PG{row.id:06d}"

        # Check idempotency
        existing = sessions_col.find_one({"session_id": session_id})
        if existing:
            skipped_count += 1
            continue

        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Parse evidence safely
        evidence_list = row.evidence if isinstance(row.evidence, list) else []

        # Construct MongoDB multi-turn session document
        turn_1 = {
            "turn_id": 1,
            "question": row.question,
            "intent": row.intent or "unknown",
            "mode": row.mode or "deterministic",
            "grounded": True,
            "answer": row.answer or "",
            "evidence": evidence_list,
            "suggested_questions": [],
            "feedback": None,
            "created_at": created_at,
        }

        # Derive initial title from question snippet
        q_snippet = (row.question[:45] + "…") if len(row.question) > 45 else row.question
        title = f"Migrated: {q_snippet}"

        session_doc: dict[str, Any] = {
            "session_id": session_id,
            "title": title,
            "analyst": "migrated_legacy",
            "scope_context": {
                "test_run_id": None,
                "run_id": None,
                "trace_id": None,
                "agent_id": None,
                "agent_version": None,
                "baseline_version": None,
            },
            "status": "ARCHIVED",  # Legacy single turns are marked ARCHIVED by default
            "turn_count": 1,
            "turns": [turn_1],
            "tags": ["migrated", "postgresql-legacy"],
            "created_at": created_at,
            "updated_at": created_at,
        }

        if dry_run:
            log.info("[DRY-RUN] Would insert session: %s ('%s')", session_id, title)
            migrated_count += 1
        else:
            try:
                sessions_col.insert_one(session_doc)
                migrated_count += 1
            except Exception as exc:
                log.error("Failed to insert session %s: %s", session_id, exc)
                error_count += 1

    summary = {
        "total_legacy_rows": total_legacy,
        "migrated": migrated_count,
        "skipped_already_present": skipped_count,
        "errors": error_count,
    }
    log.info("Migration finished: %s", summary)
    return summary


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    migrate(dry_run=is_dry)
