"""Utility script to inspect MongoDB collections and security cases in AgentShield."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path when executed directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from common.settings import get_settings


def _json_serial(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__str__"):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def inspect_mongodb(case_id: str | null = None, verbose: bool = False) -> None:
    settings = get_settings()
    print("=" * 70)
    print("AgentShield MongoDB Inspector")
    print(f"Connecting to: {settings.mongo_uri.split('@')[-1]}")  # redact credentials
    print(f"Target Database: {settings.mongo_db}")
    print("=" * 70)

    try:
        client: MongoClient[dict[str, Any]] = MongoClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=3000,
            connectTimeoutMS=3000,
        )
        # Verify server connection
        client.admin.command("ping")
        print("[OK] Connected to MongoDB server successfully!\n")
    except PyMongoError as err:
        print(f"[ERROR] Failed to connect to MongoDB: {err}")
        print("  Ensure the MongoDB service or container is running: docker compose up -d mongodb")
        sys.exit(1)

    db = client[settings.mongo_db]
    collections = db.list_collection_names()
    print(f"Collections in '{settings.mongo_db}': {collections or 'None'}")

    cases_col = db["security_cases"]
    count = cases_col.count_documents({})
    print(f"Total documents in 'security_cases': {count}\n")

    if count == 0:
        print("No cases found in 'security_cases'.")
        print("Tip: Escalate a finding from the UI (Security -> Findings -> Escalate),")
        print("     or POST to /api/v1/cases to create a new case.")
        return

    # Print summary table of cases
    print("-" * 70)
    print(f"{'CASE ID':<20} {'STATUS':<14} {'SEV':<10} {'PRI':<6} {'AGENT':<18} {'ASSIGNEE'}")
    print("-" * 70)
    for doc in cases_col.find().sort("created_at", -1).limit(20):
        cid = doc.get("case_id", "N/A")
        status = doc.get("status", "N/A")
        sev = doc.get("severity", "N/A")
        pri = doc.get("priority", "N/A")
        agent = (doc.get("target_agent") or {}).get("agent_id", "N/A")
        analyst = (doc.get("assigned_analyst") or {}).get("username", "Unassigned")
        print(f"{cid:<20} {status:<14} {sev:<10} {pri:<6} {agent:<18} {analyst}")
    print("-" * 70)

    # Detailed view
    target_doc = None
    if case_id:
        target_doc = cases_col.find_one({"case_id": case_id})
        if not target_doc:
            print(f"\nCase '{case_id}' not found.")
            return
    elif verbose or count > 0:
        target_doc = cases_col.find_one(sort=[("created_at", -1)])

    if target_doc:
        target_doc["_id"] = str(target_doc["_id"])
        print(f"\nSample Case Document ({target_doc.get('case_id')}):")
        print(json.dumps(target_doc, indent=2, default=_json_serial))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect MongoDB security cases in AgentShield")
    parser.add_argument("--case-id", type=str, help="Specific case ID to view in full JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print full JSON of the latest case")
    args = parser.parse_args()

    inspect_mongodb(case_id=args.case_id, verbose=args.verbose)
