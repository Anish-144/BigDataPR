"""Security investigation case management router (MongoDB-backed).

Provides operational incident management for security findings and anomaly alerts.
Analytical facts reside in Iceberg; MongoDB stores mutable case files, collaborative
analyst timelines, polymorphic evidence attachments, and remediation tracking.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.app.mongo import CASES_COLLECTION, get_cases_collection
from backend.app.services import query_service as qs

log = logging.getLogger("agentshield.cases")
router = APIRouter(prefix="/api/v1/cases", tags=["cases"])

CASE_ID_PATTERN = r"^CASE-[0-9]{6}-[0-9a-fA-F]{4,8}$"
AGENT_ID_PATTERN = r"^[a-z0-9\-]{3,64}$"
USER_PATTERN = r"^[A-Za-z0-9_.\-]{1,64}$"
RULE_ID_PATTERN = r"^SEC-\d{3}$"
T = "lakehouse.analytics"

CaseStatus = Literal["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING", "RESOLVED", "DISMISSED"]
CaseSeverity = Literal["low", "medium", "high", "critical"]
CasePriority = Literal["P1", "P2", "P3", "P4"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_case_id() -> str:
    ym = _now().strftime("%Y%m")
    rnd = secrets.token_hex(2)  # 4 hex chars
    return f"CASE-{ym}-{rnd}"


def _serialize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    out = dict(doc)
    if "_id" in out:
        out["id"] = str(out.pop("_id"))

    def _convert(val: Any) -> Any:
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, dict):
            return {k: _convert(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_convert(v) for v in val]
        return val

    return _convert(out)


# ---------------------------------------------------------------------------
# Pydantic Request / Response Models
# ---------------------------------------------------------------------------


class TargetAgentIn(BaseModel):
    agent_id: str = Field(..., pattern=AGENT_ID_PATTERN)
    agent_version: str = Field(..., pattern=r"^[0-9.]{1,16}$")
    workload_type: str | None = Field(None, pattern=r"^(qa|rag|tool|multi_step)$")
    model_name: str | None = Field(None, max_length=64)


class LinkedFindingIn(BaseModel):
    finding_id: str = Field(..., min_length=3, max_length=80)
    rule_id: str = Field(..., pattern=RULE_ID_PATTERN)
    rule_name: str | None = Field(None, max_length=128)
    severity: CaseSeverity = "medium"
    trace_id: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(None, pattern=r"^[0-9a-f]{16}$")
    event_time: str | None = None


class LinkedAlertIn(BaseModel):
    alert_id: str = Field(..., pattern=r"^A-[0-9a-f]{16}$")
    anomaly_type: str = Field(..., min_length=3, max_length=64)
    score: float = Field(0.0, ge=0.0, le=10.0)
    detector: str = Field(..., min_length=3, max_length=80)


class EvidenceItemIn(BaseModel):
    evidence_id: str | None = Field(None, max_length=32)
    kind: Literal["canary_leak", "policy_denial", "prompt_injection", "tool_trace", "log_diff", "custom"] = "custom"
    title: str = Field(..., min_length=3, max_length=128)
    detail: str = Field("", max_length=2000)
    ref: str | None = Field(None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalystIn(BaseModel):
    username: str = Field(..., pattern=USER_PATTERN)
    email: str | None = Field(None, max_length=128)


class RemediationIn(BaseModel):
    recommended_action: str = Field(..., min_length=3, max_length=256)
    policy_file: str | None = Field("config/policies.yaml", max_length=128)
    target_tool: str | None = Field(None, max_length=64)
    requires_code_freeze: bool = False
    completed: bool = False


class CreateCaseRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=256)
    case_id: str | None = Field(None, pattern=CASE_ID_PATTERN)
    severity: CaseSeverity = "medium"
    priority: CasePriority = "P2"
    target_agent: TargetAgentIn
    assigned_analyst: AnalystIn | None = None
    linked_findings: list[LinkedFindingIn] = Field(default_factory=list)
    linked_anomaly_alerts: list[LinkedAlertIn] = Field(default_factory=list)
    evidence_bundle: list[EvidenceItemIn] = Field(default_factory=list)
    initial_notes: str | None = Field(None, max_length=2000)
    remediation: RemediationIn | None = None
    tags: list[str] = Field(default_factory=list)
    created_by: str = Field("analyst", pattern=USER_PATTERN)


class UpdateCaseRequest(BaseModel):
    status: CaseStatus | None = None
    severity: CaseSeverity | None = None
    priority: CasePriority | None = None
    assigned_analyst: AnalystIn | None = None
    remediation: RemediationIn | None = None
    tags: list[str] | None = None
    updated_by: str = Field("analyst", pattern=USER_PATTERN)
    notes: str | None = Field(None, max_length=2000)


class AddTimelineNoteRequest(BaseModel):
    action: str = Field("INVESTIGATION_NOTE", min_length=2, max_length=64)
    notes: str = Field(..., min_length=1, max_length=2000)
    author: str = Field("analyst", pattern=USER_PATTERN)


class EscalateFindingRequest(BaseModel):
    finding_id: str = Field(..., min_length=3, max_length=80)
    priority: CasePriority = "P1"
    initial_notes: str | None = Field(None, max_length=2000)
    created_by: str = Field("analyst", pattern=USER_PATTERN)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_cases(
    status: CaseStatus | None = None,
    severity: CaseSeverity | None = None,
    priority: CasePriority | None = None,
    agent_id: str | None = Query(None, pattern=AGENT_ID_PATTERN),
    rule_id: str | None = Query(None, pattern=RULE_ID_PATTERN),
    assigned_to: str | None = Query(None, pattern=USER_PATTERN),
    search: str | None = Query(None, max_length=100),
    sort: Literal["recent", "priority", "severity", "updated"] = "recent",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100000),
) -> dict[str, Any]:
    """Search and filter operational security cases from MongoDB."""
    query: dict[str, Any] = {}
    if status is not None:
        query["status"] = status
    if severity is not None:
        query["severity"] = severity
    if priority is not None:
        query["priority"] = priority
    if agent_id is not None:
        query["target_agent.agent_id"] = agent_id
    if rule_id is not None:
        query["linked_findings.rule_id"] = rule_id
    if assigned_to is not None:
        query["assigned_analyst.username"] = assigned_to
    if search:
        query["$text"] = {"$search": search}

    sort_criteria = {
        "recent": [("created_at", -1)],
        "updated": [("updated_at", -1)],
        "priority": [("priority", 1), ("created_at", -1)],
        "severity": [("severity", 1), ("created_at", -1)],
    }[sort]

    try:
        col = get_cases_collection()
        total = col.count_documents(query)
        cursor = col.find(query).sort(sort_criteria).skip(offset).limit(limit)
        rows = [_serialize_doc(doc) for doc in cursor]
        return {
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(rows)) < total,
        }
    except PyMongoError as exc:
        log.error("MongoDB query failure in list_cases: %s", exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.get("/summary/analytics")
def case_analytics() -> dict[str, Any]:
    """Operational KPI summary computed live via MongoDB aggregation pipelines.

    Computes:
    - Open vs resolved case breakdown
    - Distribution by severity and priority
    - Unresolved cases grouped by target agent
    - Mean Time to Remediation (MTTR) in hours
    - Most frequently breached policy rules
    """
    try:
        col = get_cases_collection()

        # Pipeline 1: status counts
        status_counts = {
            r["_id"]: r["count"]
            for r in col.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
            if r["_id"] is not None
        }

        # Pipeline 2: severity counts
        severity_counts = {
            r["_id"]: r["count"]
            for r in col.aggregate([{"$group": {"_id": "$severity", "count": {"$sum": 1}}}])
            if r["_id"] is not None
        }

        # Pipeline 3: unresolved cases by agent
        by_agent = list(
            col.aggregate([
                {"$match": {"status": {"$in": ["OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING"]}}},
                {
                    "$group": {
                        "_id": {
                            "agent_id": "$target_agent.agent_id",
                            "agent_version": "$target_agent.agent_version",
                        },
                        "unresolved_cases": {"$sum": 1},
                        "critical_cases": {
                            "$sum": {"$cond": [{"$eq": ["$severity", "critical"]}, 1, 0]}
                        },
                    }
                },
                {
                    "$project": {
                        "agent_id": "$_id.agent_id",
                        "agent_version": "$_id.agent_version",
                        "unresolved_cases": 1,
                        "critical_cases": 1,
                        "_id": 0,
                    }
                },
                {"$sort": {"critical_cases": -1, "unresolved_cases": -1}},
                {"$limit": 10},
            ])
        )

        # Pipeline 4: Mean Time to Remediation (MTTR) in hours
        mttr_rows = list(
            col.aggregate([
                {"$match": {"status": "RESOLVED", "remediation.completed": True}},
                {
                    "$project": {
                        "severity": 1,
                        "duration_hours": {
                            "$divide": [{"$subtract": ["$updated_at", "$created_at"]}, 3600000]
                        },
                    }
                },
                {
                    "$group": {
                        "_id": "$severity",
                        "resolved_cases": {"$sum": 1},
                        "avg_hours": {"$avg": "$duration_hours"},
                    }
                },
            ])
        )
        mttr = {r["_id"]: round(r["avg_hours"], 1) for r in mttr_rows}

        # Pipeline 5: Most breached rules in linked findings
        top_rules = list(
            col.aggregate([
                {"$unwind": "$linked_findings"},
                {
                    "$group": {
                        "_id": "$linked_findings.rule_id",
                        "rule_name": {"$first": "$linked_findings.rule_name"},
                        "breach_count": {"$sum": 1},
                    }
                },
                {"$sort": {"breach_count": -1}},
                {"$limit": 5},
                {"$project": {"rule_id": "$_id", "rule_name": 1, "breach_count": 1, "_id": 0}},
            ])
        )

        total_open = sum(
            v for k, v in status_counts.items() if k in {"OPEN", "TRIAGED", "IN_REVIEW", "REMEDIATION_PENDING"}
        )

        return {
            "total_open_cases": total_open,
            "status_breakdown": status_counts,
            "severity_breakdown": severity_counts,
            "by_agent": by_agent,
            "mttr_hours_by_severity": mttr,
            "top_breached_rules": top_rules,
        }
    except PyMongoError as exc:
        log.error("MongoDB aggregation failure in case_analytics: %s", exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("", status_code=201)
def create_case(body: CreateCaseRequest) -> dict[str, Any]:
    """Create a new operational security investigation case in MongoDB."""
    case_id = body.case_id or _gen_case_id()
    now = _now()

    # Build initial timeline entry
    timeline_entry = {
        "timestamp": now,
        "author": body.created_by,
        "action": "CASE_CREATED",
        "notes": body.initial_notes or f"Case opened with priority {body.priority} and severity {body.severity}.",
    }

    analyst_doc = None
    if body.assigned_analyst:
        analyst_doc = {
            "username": body.assigned_analyst.username,
            "email": body.assigned_analyst.email,
            "assigned_at": now,
        }

    remediation_doc = None
    if body.remediation:
        remediation_doc = body.remediation.model_dump()

    doc: dict[str, Any] = {
        "case_id": case_id,
        "title": body.title,
        "status": "OPEN",
        "severity": body.severity,
        "priority": body.priority,
        "assigned_analyst": analyst_doc,
        "target_agent": body.target_agent.model_dump(),
        "linked_findings": [f.model_dump() for f in body.linked_findings],
        "linked_anomaly_alerts": [a.model_dump() for a in body.linked_anomaly_alerts],
        "evidence_bundle": [e.model_dump() for e in body.evidence_bundle],
        "timeline": [timeline_entry],
        "remediation": remediation_doc,
        "tags": body.tags,
        "created_at": now,
        "updated_at": now,
    }

    try:
        col = get_cases_collection()
        col.insert_one(doc)
        return _serialize_doc(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(409, {"code": "case_exists", "message": f"Case ID {case_id} already exists"}) from exc
    except PyMongoError as exc:
        log.error("MongoDB insert failure in create_case: %s", exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("/escalate-finding", status_code=201)
def escalate_finding(body: EscalateFindingRequest) -> dict[str, Any]:
    """Promote an immutable security finding from the Lakehouse into a mutable operational Case.

    Queries Trino lakehouse for the finding and associated span/trace, then creates
    the linked Case document in MongoDB.
    """
    sql = f"""
        SELECT finding_id, rule_id, rule_name, category, severity, agent_id, agent_version,
               test_run_id, run_id, trace_id, span_id, tool_name, action, detector, evidence,
               event_time
        FROM {T}.agent_security_findings WHERE finding_id = ? LIMIT 1"""
    rows = qs.sql_rows(sql, [body.finding_id])
    if not rows:
        raise HTTPException(404, {"code": "finding_not_found", "message": f"Finding {body.finding_id} not found"})

    f = rows[0]
    title = f"Investigation: {f.get('rule_name') or f.get('rule_id')} on {f.get('agent_id')} ({f.get('agent_version')})"
    sev = f.get("severity") or "high"
    if sev not in {"low", "medium", "high", "critical"}:
        sev = "high"

    evidence_items = []
    if f.get("evidence"):
        evidence_items.append(
            EvidenceItemIn(
                evidence_id="EV-01",
                kind="policy_denial" if f.get("action") == "blocked" else "custom",
                title=f"Detector Evidence ({f.get('detector')})",
                detail=f.get("evidence")[:1000],
                ref=f.get("finding_id"),
            )
        )

    linked_finding = LinkedFindingIn(
        finding_id=f["finding_id"],
        rule_id=f["rule_id"],
        rule_name=f.get("rule_name"),
        severity=sev,
        trace_id=f["trace_id"],
        span_id=f.get("span_id"),
        event_time=str(f.get("event_time") or ""),
    )

    create_req = CreateCaseRequest(
        title=title,
        severity=sev,
        priority=body.priority,
        target_agent=TargetAgentIn(agent_id=f["agent_id"], agent_version=f["agent_version"]),
        linked_findings=[linked_finding],
        evidence_bundle=evidence_items,
        initial_notes=body.initial_notes or f"Escalated from {f['finding_id']} (Rule {f['rule_id']}).",
        created_by=body.created_by,
        tags=[f["rule_id"], f.get("category") or "security"],
    )
    return create_case(create_req)


@router.get("/{case_id}")
def get_case(
    case_id: str = Path(..., pattern=CASE_ID_PATTERN),
    enrich: bool = Query(False, description="Enrich with live Lakehouse trace details"),
) -> dict[str, Any]:
    """Retrieve full details of an operational security case by case_id."""
    try:
        col = get_cases_collection()
        doc = col.find_one({"case_id": case_id})
        if not doc:
            raise HTTPException(404, {"code": "case_not_found", "message": f"Case {case_id} not found"})
        data = _serialize_doc(doc)

        if enrich and data and data.get("linked_findings"):
            # Optional Lakehouse trace enrichment
            trace_ids = list({f["trace_id"] for f in data["linked_findings"] if f.get("trace_id")})[:5]
            if trace_ids:
                ph = ", ".join(["?"] * len(trace_ids))
                runs = qs.sql_rows(
                    f"SELECT trace_id, run_id, latency_ms, status, task_success FROM {T}.agent_run_metrics WHERE trace_id IN ({ph})",
                    trace_ids,
                )
                data["enriched_traces"] = runs

        return data
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB get failure for case %s: %s", case_id, exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.patch("/{case_id}")
def update_case(body: UpdateCaseRequest, case_id: str = Path(..., pattern=CASE_ID_PATTERN)) -> dict[str, Any]:
    """Atomically update case attributes and append an audit timeline note."""
    now = _now()
    updates: dict[str, Any] = {"updated_at": now}
    new_timeline_entries: list[dict[str, Any]] = []

    try:
        col = get_cases_collection()
        current = col.find_one({"case_id": case_id})
        if not current:
            raise HTTPException(404, {"code": "case_not_found", "message": f"Case {case_id} not found"})

        if body.status is not None and body.status != current.get("status"):
            updates["status"] = body.status
            note_text = body.notes or f"Status transitioned from {current.get('status')} to {body.status}."
            new_timeline_entries.append({
                "timestamp": now,
                "author": body.updated_by,
                "action": f"STATUS_CHANGE_{body.status}",
                "notes": note_text,
            })

        if body.severity is not None:
            updates["severity"] = body.severity
        if body.priority is not None:
            updates["priority"] = body.priority

        if body.assigned_analyst is not None:
            updates["assigned_analyst"] = {
                "username": body.assigned_analyst.username,
                "email": body.assigned_analyst.email,
                "assigned_at": now,
            }
            new_timeline_entries.append({
                "timestamp": now,
                "author": body.updated_by,
                "action": "ANALYST_ASSIGNED",
                "notes": f"Case assigned to {body.assigned_analyst.username}.",
            })

        if body.remediation is not None:
            rem_doc = body.remediation.model_dump()
            if rem_doc.get("completed") and not current.get("remediation", {}).get("completed"):
                rem_doc["completed_at"] = now
                rem_doc["completed_by"] = body.updated_by
                new_timeline_entries.append({
                    "timestamp": now,
                    "author": body.updated_by,
                    "action": "REMEDIATION_COMPLETED",
                    "notes": f"Action '{rem_doc.get('recommended_action')}' verified and completed.",
                })
            updates["remediation"] = rem_doc

        if body.tags is not None:
            updates["tags"] = body.tags

        # If user gave generic notes without a status/assignment change
        if body.notes and not new_timeline_entries:
            new_timeline_entries.append({
                "timestamp": now,
                "author": body.updated_by,
                "action": "CASE_UPDATED",
                "notes": body.notes,
            })

        mongo_update: dict[str, Any] = {"$set": updates}
        if new_timeline_entries:
            mongo_update["$push"] = {"timeline": {"$each": new_timeline_entries}}

        res = col.find_one_and_update(
            {"case_id": case_id},
            mongo_update,
            return_document=True,
        )
        return _serialize_doc(res)
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB update failure for case %s: %s", case_id, exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("/{case_id}/timeline", status_code=201)
def add_timeline_note(
    body: AddTimelineNoteRequest, case_id: str = Path(..., pattern=CASE_ID_PATTERN)
) -> dict[str, Any]:
    """Append an analyst note to the case timeline using atomic $push."""
    now = _now()
    entry = {
        "timestamp": now,
        "author": body.author,
        "action": body.action,
        "notes": body.notes,
    }

    try:
        col = get_cases_collection()
        res = col.find_one_and_update(
            {"case_id": case_id},
            {"$push": {"timeline": entry}, "$set": {"updated_at": now}},
            return_document=True,
        )
        if not res:
            raise HTTPException(404, {"code": "case_not_found", "message": f"Case {case_id} not found"})

        entry_serialized = dict(entry)
        entry_serialized["timestamp"] = now.isoformat()
        return {"case_id": case_id, "timeline_entry": entry_serialized}
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB timeline push failure for case %s: %s", case_id, exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("/{case_id}/findings", status_code=200)
def link_finding_to_case(
    body: LinkedFindingIn, case_id: str = Path(..., pattern=CASE_ID_PATTERN)
) -> dict[str, Any]:
    """Link an additional security finding to an active case document."""
    now = _now()
    audit_entry = {
        "timestamp": now,
        "author": "analyst",
        "action": "FINDING_LINKED",
        "notes": f"Linked finding {body.finding_id} (Rule {body.rule_id}, Trace {body.trace_id[:8]}...).",
    }

    try:
        col = get_cases_collection()
        case_doc = col.find_one({"case_id": case_id})
        if not case_doc:
            raise HTTPException(404, {"code": "case_not_found", "message": f"Case {case_id} not found"})

        # Prevent duplicate findings
        existing_ids = {f.get("finding_id") for f in case_doc.get("linked_findings", [])}
        if body.finding_id in existing_ids:
            return {"case_id": case_id, "message": "Finding already linked", "linked_findings": case_doc.get("linked_findings")}

        res = col.find_one_and_update(
            {"case_id": case_id},
            {
                "$push": {
                    "linked_findings": body.model_dump(),
                    "timeline": audit_entry,
                },
                "$set": {"updated_at": now},
            },
            return_document=True,
        )
        return _serialize_doc(res)
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB link finding failure for case %s: %s", case_id, exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("/{case_id}/evidence", status_code=201)
def add_evidence_item(
    body: EvidenceItemIn, case_id: str = Path(..., pattern=CASE_ID_PATTERN)
) -> dict[str, Any]:
    """Attach an evidence artifact to the case evidence bundle."""
    now = _now()
    ev_id = body.evidence_id or f"EV-{secrets.token_hex(2).upper()}"
    ev_doc = body.model_dump()
    ev_doc["evidence_id"] = ev_id

    audit_entry = {
        "timestamp": now,
        "author": "analyst",
        "action": "EVIDENCE_ATTACHED",
        "notes": f"Attached evidence {ev_id}: {body.title} ({body.kind}).",
    }

    try:
        col = get_cases_collection()
        res = col.find_one_and_update(
            {"case_id": case_id},
            {
                "$push": {
                    "evidence_bundle": ev_doc,
                    "timeline": audit_entry,
                },
                "$set": {"updated_at": now},
            },
            return_document=True,
        )
        if not res:
            raise HTTPException(404, {"code": "case_not_found", "message": f"Case {case_id} not found"})
        return {"case_id": case_id, "evidence_id": ev_id, "evidence_item": ev_doc}
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB add evidence failure for case %s: %s", case_id, exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.delete("/{case_id}")
def delete_case(case_id: str = Path(..., pattern=CASE_ID_PATTERN)) -> dict[str, Any]:
    """Delete a case document (used primarily for test cleanup and management)."""
    try:
        col = get_cases_collection()
        res = col.delete_one({"case_id": case_id})
        if res.deleted_count == 0:
            raise HTTPException(404, {"code": "case_not_found", "message": f"Case {case_id} not found"})
        return {"case_id": case_id, "deleted": True}
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB delete failure for case %s: %s", case_id, exc)
        raise HTTPException(
            503, {"code": "case_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc
