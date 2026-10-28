"""AI investigation assistant and multi-turn session memory API (MongoDB + PostgreSQL).

Provides:
- Legacy single-turn evidence-grounded investigation endpoint (/api/v1/investigations).
- Stateful multi-turn investigation session store backed by MongoDB 7.0 (/api/v1/investigations/sessions).
- Structured evidence citation tracking, turn-level feedback rating/verdict via arrayFilters,
  and aggregation pipelines for assistant evaluation analytics.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError, PyMongoError
from sqlalchemy import select

from backend.app import db
from backend.app.mongo import SESSIONS_COLLECTION, get_sessions_collection
from common import llm
from investigation import answer_service as svc
from investigation.retrieval import retriever

log = logging.getLogger("agentshield.investigations")
router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])

SESSION_ID_PATTERN = r"^SESS-[0-9]{6}-[0-9a-fA-F]{4,8}$"
USER_PATTERN = r"^[A-Za-z0-9_.\-]{1,64}$"
AGENT_ID_PATTERN = r"^[a-z0-9\-]{3,64}$"

SessionStatus = Literal["ACTIVE", "ARCHIVED", "CLOSED"]
FeedbackVerdict = Literal["accurate", "hallucination", "incomplete"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_session_id() -> str:
    ym = _now().strftime("%Y%m")
    rnd = secrets.token_hex(3)  # 6 hex chars
    return f"SESS-{ym}-{rnd}"


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


class ContextIn(BaseModel):
    test_run_id: str | None = Field(None, pattern=r"^TR-\d{8}-[0-9a-f]{6}$")
    run_id: str | None = Field(None, pattern=r"^R-[0-9a-f]{6}-\d{6}$")
    trace_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    agent_id: str | None = Field(None, pattern=r"^[a-z0-9\-]{3,64}$")
    agent_version: str | None = Field(None, pattern=r"^\d+\.\d+\.\d+$")
    baseline_version: str | None = Field(None, pattern=r"^\d+\.\d+\.\d+$")


class InvestigationIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    context: ContextIn = Field(default_factory=ContextIn)
    use_llm: bool = True
    session_id: str | None = Field(None, pattern=SESSION_ID_PATTERN)


class CreateSessionRequest(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=256)
    analyst: str = Field("analyst", pattern=USER_PATTERN)
    scope_context: ContextIn = Field(default_factory=ContextIn)
    initial_question: str | None = Field(None, min_length=1, max_length=1000)
    use_llm: bool = True
    tags: list[str] = Field(default_factory=list)


class AddTurnRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    use_llm: bool = True
    author: str = Field("analyst", pattern=USER_PATTERN)
    context_override: ContextIn | None = None


class SubmitFeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    verdict: FeedbackVerdict
    notes: str | None = Field(None, max_length=1000)
    submitted_by: str = Field("analyst", pattern=USER_PATTERN)


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=256)
    status: SessionStatus | None = None
    tags: list[str] | None = None


# ---------------------------------------------------------------------------
# Legacy Endpoints (PostgreSQL + Assistant Compatibility)
# ---------------------------------------------------------------------------


@router.post("")
def investigate(body: InvestigationIn) -> dict:
    """Answer an investigation question from lakehouse evidence and local runbooks.

    Evidence is gathered only through fixed, parameterised queries; no SQL is generated from the question.
    Saves record to PostgreSQL for legacy audit log, and into MongoDB if a session is active.
    """
    try:
        ans = svc.investigate(body.question, svc.Context(**body.context.model_dump()), use_llm=body.use_llm)
    except Exception as exc:
        raise HTTPException(
            503, {"code": "investigation_failed", "message": f"{type(exc).__name__}: {exc}"[:500]}
        ) from exc

    out = ans.to_dict()

    # Legacy PostgreSQL audit log
    try:
        with db.session_factory()() as s:
            s.add(
                db.InvestigationLog(
                    question=body.question,
                    intent=ans.intent,
                    answer=ans.answer,
                    evidence=out["evidence"],
                    mode=ans.mode,
                )
            )
            s.commit()
    except Exception:
        out["warning"] = "investigation history not saved to relational store"

    # If session_id was provided, also record turn into MongoDB session
    if body.session_id:
        try:
            col = get_sessions_collection()
            sess = col.find_one({"session_id": body.session_id})
            if sess and sess.get("status") == "ACTIVE":
                now = _now()
                turn_id = (sess.get("turn_count") or 0) + 1
                turn_doc = {
                    "turn_id": turn_id,
                    "question": body.question,
                    "intent": ans.intent,
                    "mode": ans.mode,
                    "grounded": ans.grounded,
                    "answer": ans.answer,
                    "evidence": out.get("evidence", []),
                    "suggested_questions": out.get("suggested_questions", []),
                    "feedback": None,
                    "created_at": now,
                }
                col.find_one_and_update(
                    {"session_id": body.session_id},
                    {
                        "$push": {"turns": turn_doc},
                        "$inc": {"turn_count": 1},
                        "$set": {"updated_at": now},
                    },
                )
                out["session_id"] = body.session_id
                out["turn_id"] = turn_id
        except Exception as exc:
            log.warning("Could not sync turn to MongoDB session %s: %s", body.session_id, exc)

    return out


@router.get("/examples")
def examples() -> dict:
    return {
        "examples": svc.EXAMPLES,
        "llm_enabled": llm.llm_enabled(),
        "llm_model": llm.model_name() if llm.llm_enabled() else None,
        "retrieval_backend": retriever().backend,
    }


@router.get("/history")
def history(limit: int = Query(20, ge=1, le=200)) -> dict:
    """Historical single-turn investigations from PostgreSQL."""
    try:
        with db.session_factory()() as s:
            rows = (
                s.scalars(
                    select(db.InvestigationLog).order_by(db.InvestigationLog.created_at.desc()).limit(limit)
                ).all()
            )
    except Exception as exc:
        raise HTTPException(503, {"code": "history_unavailable", "message": str(exc)[:300]}) from exc
    return {
        "items": [
            {
                "id": r.id,
                "question": r.question,
                "intent": r.intent,
                "mode": r.mode,
                "answer": r.answer,
                "evidence": r.evidence,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# MongoDB-backed Multi-Turn Investigation Sessions
# ---------------------------------------------------------------------------


@router.get("/sessions")
def list_sessions(
    status: SessionStatus | None = None,
    analyst: str | None = Query(None, pattern=USER_PATTERN),
    agent_id: str | None = Query(None, pattern=AGENT_ID_PATTERN),
    test_run_id: str | None = None,
    trace_id: str | None = None,
    search: str | None = Query(None, max_length=100),
    sort: Literal["recent", "updated", "turns"] = "updated",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List, search, filter, and paginate multi-turn investigation sessions from MongoDB."""
    query: dict[str, Any] = {}
    if status is not None:
        query["status"] = status
    if analyst is not None:
        query["analyst"] = analyst
    if agent_id is not None:
        query["scope_context.agent_id"] = agent_id
    if test_run_id is not None:
        query["scope_context.test_run_id"] = test_run_id
    if trace_id is not None:
        query["scope_context.trace_id"] = trace_id
    if search:
        query["$text"] = {"$search": search}

    sort_criteria = {
        "recent": [("created_at", -1)],
        "updated": [("updated_at", -1)],
        "turns": [("turn_count", -1), ("updated_at", -1)],
    }[sort]

    try:
        col = get_sessions_collection()
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
        log.error("MongoDB query failure in list_sessions: %s", exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.get("/sessions/summary/analytics")
def session_analytics() -> dict[str, Any]:
    """Operational evaluation metrics computed live via MongoDB aggregation pipelines.

    Computes:
    - Session counts by status
    - Total turns and average turns per session
    - Average feedback rating and ratings count
    - Feedback verdict breakdown (accurate, hallucination, incomplete)
    - Turn mode breakdown (deterministic vs llm)
    - Groundedness ratio
    - Session depth distribution ($bucket)
    - Top investigated agent cohorts
    - Top question intents
    """
    try:
        col = get_sessions_collection()

        # Pipeline 1: status counts
        status_counts = {
            r["_id"]: r["count"]
            for r in col.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
            if r["_id"] is not None
        }

        # Pipeline 2: multi-faceted evaluation metrics via $facet (with fallback for test mocks)
        try:
            eval_metrics = list(
                col.aggregate([
                    {"$unwind": "$turns"},
                    {
                        "$facet": {
                            "ratings_summary": [
                                {"$match": {"turns.feedback.rating": {"$exists": True, "$ne": None}}},
                                {
                                    "$group": {
                                        "_id": None,
                                        "avg_rating": {"$avg": "$turns.feedback.rating"},
                                        "ratings_count": {"$sum": 1},
                                    }
                                },
                            ],
                            "verdicts_breakdown": [
                                {"$match": {"turns.feedback.verdict": {"$exists": True, "$ne": None}}},
                                {"$group": {"_id": "$turns.feedback.verdict", "count": {"$sum": 1}}},
                            ],
                            "mode_breakdown": [
                                {"$group": {"_id": "$turns.mode", "count": {"$sum": 1}}},
                            ],
                            "groundedness": [
                                {"$group": {"_id": "$turns.grounded", "count": {"$sum": 1}}},
                            ],
                            "top_intents": [
                                {"$group": {"_id": "$turns.intent", "count": {"$sum": 1}}},
                                {"$sort": {"count": -1}},
                                {"$limit": 6},
                                {"$project": {"intent": "$_id", "count": 1, "_id": 0}},
                            ],
                        }
                    },
                ])
            )
            facet_data = eval_metrics[0] if eval_metrics else {}
        except Exception:
            # Fallback for mock environments lacking $facet
            try:
                ratings_rows = list(col.aggregate([
                    {"$unwind": "$turns"},
                    {"$match": {"turns.feedback.rating": {"$exists": True, "$ne": None}}},
                    {"$group": {"_id": None, "avg_rating": {"$avg": "$turns.feedback.rating"}, "ratings_count": {"$sum": 1}}},
                ]))
            except Exception:
                ratings_rows = []
            try:
                verdict_rows = list(col.aggregate([
                    {"$unwind": "$turns"},
                    {"$match": {"turns.feedback.verdict": {"$exists": True, "$ne": None}}},
                    {"$group": {"_id": "$turns.feedback.verdict", "count": {"$sum": 1}}},
                ]))
            except Exception:
                verdict_rows = []
            try:
                mode_rows = list(col.aggregate([
                    {"$unwind": "$turns"},
                    {"$group": {"_id": "$turns.mode", "count": {"$sum": 1}}},
                ]))
            except Exception:
                mode_rows = []
            try:
                grounded_rows = list(col.aggregate([
                    {"$unwind": "$turns"},
                    {"$group": {"_id": "$turns.grounded", "count": {"$sum": 1}}},
                ]))
            except Exception:
                grounded_rows = []
            try:
                intent_rows = list(col.aggregate([
                    {"$unwind": "$turns"},
                    {"$group": {"_id": "$turns.intent", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": 6},
                ]))
            except Exception:
                intent_rows = []
            facet_data = {
                "ratings_summary": ratings_rows,
                "verdicts_breakdown": verdict_rows,
                "mode_breakdown": mode_rows,
                "groundedness": grounded_rows,
                "top_intents": [{"intent": r["_id"], "count": r["count"]} for r in intent_rows if r.get("_id")],
            }

        # Pipeline 3: session depth histogram via $bucket (with fallback for test mocks)
        try:
            depth_buckets = list(
                col.aggregate([
                    {
                        "$bucket": {
                            "groupBy": "$turn_count",
                            "boundaries": [0, 2, 5, 10, 20],
                            "default": "20+",
                            "output": {"sessions": {"$sum": 1}},
                        }
                    }
                ])
            )
        except Exception:
            depth_buckets = []

        # Pipeline 4: top investigated agents
        try:
            top_agents = list(
                col.aggregate([
                    {"$match": {"scope_context.agent_id": {"$exists": True, "$ne": None}}},
                    {
                        "$group": {
                            "_id": {
                                "agent_id": "$scope_context.agent_id",
                                "agent_version": "$scope_context.agent_version",
                            },
                            "sessions": {"$sum": 1},
                            "total_turns": {"$sum": "$turn_count"},
                        }
                    },
                    {"$sort": {"sessions": -1, "total_turns": -1}},
                    {"$limit": 5},
                    {
                        "$project": {
                            "agent_id": "$_id.agent_id",
                            "agent_version": "$_id.agent_version",
                            "sessions": 1,
                            "total_turns": 1,
                            "_id": 0,
                        }
                    },
                ])
            )
        except Exception:
            top_agents = []

        # Format outputs
        ratings_doc = facet_data.get("ratings_summary", [{}])[0] if facet_data.get("ratings_summary") else {}
        avg_rating = round(ratings_doc.get("avg_rating"), 2) if ratings_doc.get("avg_rating") is not None else None
        ratings_count = ratings_doc.get("ratings_count", 0)

        verdicts = {r["_id"]: r["count"] for r in facet_data.get("verdicts_breakdown", []) if r.get("_id")}
        modes = {r["_id"]: r["count"] for r in facet_data.get("mode_breakdown", []) if r.get("_id")}

        grounded_dict = {r["_id"]: r["count"] for r in facet_data.get("groundedness", [])}
        total_grounded_evaluated = sum(grounded_dict.values())
        grounded_ratio = (
            round(grounded_dict.get(True, 0) / total_grounded_evaluated, 3)
            if total_grounded_evaluated > 0
            else 1.0
        )

        total_sessions = sum(status_counts.values())
        active_sessions = status_counts.get("ACTIVE", 0)
        archived_sessions = status_counts.get("ARCHIVED", 0) + status_counts.get("CLOSED", 0)

        total_turns = sum(modes.values())
        avg_turns = round(total_turns / total_sessions, 1) if total_sessions > 0 else 0.0

        depth_distribution = [
            {"depth_range": f"{b['_id']}-{int(b['_id']) + 1 if isinstance(b['_id'], int) else b['_id']}", "count": b["sessions"]}
            if isinstance(b.get("_id"), int)
            else {"depth_range": str(b.get("_id")), "count": b.get("sessions", 0)}
            for b in depth_buckets
        ]

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "archived_sessions": archived_sessions,
            "status_breakdown": status_counts,
            "total_turns": total_turns,
            "avg_turns_per_session": avg_turns,
            "avg_rating": avg_rating,
            "ratings_count": ratings_count,
            "verdicts_breakdown": verdicts,
            "mode_breakdown": modes,
            "grounded_ratio": grounded_ratio,
            "top_intents": facet_data.get("top_intents", []),
            "session_depth_distribution": depth_distribution,
            "top_investigated_agents": top_agents,
        }
    except PyMongoError as exc:
        log.error("MongoDB aggregation failure in session_analytics: %s", exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("/sessions", status_code=201)
def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create a new multi-turn investigation session in MongoDB.

    Optionally answers an initial question immediately, populating Turn 1.
    """
    now = _now()
    session_id = _gen_session_id()

    # Determine default title
    agent_info = body.scope_context.agent_id or "General System"
    title = body.title or f"Investigation: {agent_info} ({now.strftime('%b %d')})"

    turns: list[dict[str, Any]] = []
    turn_count = 0

    if body.initial_question:
        try:
            ans = svc.investigate(
                body.initial_question,
                svc.Context(**body.scope_context.model_dump()),
                use_llm=body.use_llm,
            )
            out = ans.to_dict()
            turns.append({
                "turn_id": 1,
                "question": body.initial_question,
                "intent": ans.intent,
                "mode": ans.mode,
                "grounded": ans.grounded,
                "answer": ans.answer,
                "evidence": out.get("evidence", []),
                "suggested_questions": out.get("suggested_questions", []),
                "feedback": None,
                "created_at": now,
            })
            turn_count = 1
        except Exception as exc:
            log.warning("Initial question failed during session creation: %s", exc)

    doc: dict[str, Any] = {
        "session_id": session_id,
        "title": title,
        "analyst": body.analyst,
        "scope_context": body.scope_context.model_dump(),
        "status": "ACTIVE",
        "turn_count": turn_count,
        "turns": turns,
        "tags": body.tags,
        "created_at": now,
        "updated_at": now,
    }

    try:
        col = get_sessions_collection()
        col.insert_one(doc)
        return _serialize_doc(doc)
    except DuplicateKeyError as exc:
        raise HTTPException(
            409, {"code": "session_exists", "message": f"Session ID {session_id} already exists"}
        ) from exc
    except PyMongoError as exc:
        log.error("MongoDB insert failure in create_session: %s", exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.get("/sessions/{session_id}")
def get_session(session_id: str = Path(..., pattern=SESSION_ID_PATTERN)) -> dict[str, Any]:
    """Retrieve an investigation session and its full multi-turn conversation history."""
    try:
        col = get_sessions_collection()
        doc = col.find_one({"session_id": session_id})
        if not doc:
            raise HTTPException(404, {"code": "session_not_found", "message": f"Session {session_id} not found"})
        return _serialize_doc(doc)
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB get failure for session %s: %s", session_id, exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.post("/sessions/{session_id}/turns", status_code=201)
def add_turn(
    body: AddTurnRequest,
    session_id: str = Path(..., pattern=SESSION_ID_PATTERN),
) -> dict[str, Any]:
    """Ask a question and atomically append a new conversation turn to an active session."""
    now = _now()
    try:
        col = get_sessions_collection()
        session_doc = col.find_one({"session_id": session_id})
        if not session_doc:
            raise HTTPException(404, {"code": "session_not_found", "message": f"Session {session_id} not found"})

        if session_doc.get("status") != "ACTIVE":
            raise HTTPException(
                400,
                {
                    "code": "session_not_active",
                    "message": f"Cannot append to session in state '{session_doc.get('status')}'",
                },
            )

        current_count = session_doc.get("turn_count", 0)
        if current_count >= 50:
            raise HTTPException(
                400,
                {"code": "turn_limit_exceeded", "message": "Session turn limit (50) reached. Start a new session."},
            )

        # Merge session context with optional turn override
        context_dict = dict(session_doc.get("scope_context") or {})
        if body.context_override:
            for k, v in body.context_override.model_dump().items():
                if v is not None:
                    context_dict[k] = v

        # Run investigation assistant
        ans = svc.investigate(body.question, svc.Context(**context_dict), use_llm=body.use_llm)
        out = ans.to_dict()

        turn_id = current_count + 1
        turn_doc = {
            "turn_id": turn_id,
            "question": body.question,
            "intent": ans.intent,
            "mode": ans.mode,
            "grounded": ans.grounded,
            "answer": ans.answer,
            "evidence": out.get("evidence", []),
            "suggested_questions": out.get("suggested_questions", []),
            "feedback": None,
            "created_at": now,
        }

        # Atomic append and counter increment via $push and $inc
        res = col.find_one_and_update(
            {"session_id": session_id},
            {
                "$push": {"turns": turn_doc},
                "$inc": {"turn_count": 1},
                "$set": {"updated_at": now},
            },
            return_document=True,
        )

        # Dual-write to relational store for audit history
        try:
            with db.session_factory()() as s:
                s.add(
                    db.InvestigationLog(
                        question=body.question,
                        intent=ans.intent,
                        answer=ans.answer,
                        evidence=out.get("evidence", []),
                        mode=ans.mode,
                    )
                )
                s.commit()
        except Exception:
            pass

        return {
            "session_id": session_id,
            "turn": _serialize_doc(turn_doc),
            "turn_count": res.get("turn_count", turn_id),
        }
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB turn append failure for session %s: %s", session_id, exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.patch("/sessions/{session_id}/turns/{turn_id}/feedback")
def submit_turn_feedback(
    body: SubmitFeedbackRequest,
    session_id: str = Path(..., pattern=SESSION_ID_PATTERN),
    turn_id: int = Path(..., ge=1, le=100),
) -> dict[str, Any]:
    """Submit rating, verdict, and review notes on a specific turn using MongoDB arrayFilters."""
    now = _now()
    feedback_doc = {
        "rating": body.rating,
        "verdict": body.verdict,
        "notes": body.notes,
        "submitted_at": now,
        "submitted_by": body.submitted_by,
    }

    try:
        col = get_sessions_collection()
        # Surgical update to specific matched array element using arrayFilters
        try:
            res = col.find_one_and_update(
                {"session_id": session_id, "turns.turn_id": turn_id},
                {
                    "$set": {
                        "turns.$[elem].feedback": feedback_doc,
                        "updated_at": now,
                    }
                },
                array_filters=[{"elem.turn_id": turn_id}],
                return_document=True,
            )
        except (TypeError, NotImplementedError):
            # Fallback for pure-python mock engines (e.g. mongomock) lacking $[elem] array_filters
            doc = col.find_one({"session_id": session_id, "turns.turn_id": turn_id})
            if not doc:
                raise HTTPException(
                    404,
                    {"code": "turn_not_found", "message": f"Turn {turn_id} in session {session_id} not found"},
                )
            for t in doc.get("turns", []):
                if t.get("turn_id") == turn_id:
                    t["feedback"] = feedback_doc
            doc["updated_at"] = now
            col.replace_one({"session_id": session_id}, doc)
            res = doc

        if not res:
            raise HTTPException(
                404,
                {"code": "turn_not_found", "message": f"Turn {turn_id} in session {session_id} not found"},
            )

        serialized = _serialize_doc(res)
        # Find updated turn
        updated_turn = next((t for t in serialized.get("turns", []) if t.get("turn_id") == turn_id), None)
        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "feedback": updated_turn.get("feedback") if updated_turn else feedback_doc,
        }
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB feedback update failure for session %s, turn %d: %s", session_id, turn_id, exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.patch("/sessions/{session_id}")
def update_session(
    body: UpdateSessionRequest,
    session_id: str = Path(..., pattern=SESSION_ID_PATTERN),
) -> dict[str, Any]:
    """Update session metadata, title, status, or tags."""
    now = _now()
    updates: dict[str, Any] = {"updated_at": now}
    if body.title is not None:
        updates["title"] = body.title
    if body.status is not None:
        updates["status"] = body.status
    if body.tags is not None:
        updates["tags"] = body.tags

    try:
        col = get_sessions_collection()
        res = col.find_one_and_update(
            {"session_id": session_id},
            {"$set": updates},
            return_document=True,
        )
        if not res:
            raise HTTPException(404, {"code": "session_not_found", "message": f"Session {session_id} not found"})
        return _serialize_doc(res)
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB update failure for session %s: %s", session_id, exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str = Path(..., pattern=SESSION_ID_PATTERN)) -> dict[str, Any]:
    """Delete an investigation session document (used for test cleanup and management)."""
    try:
        col = get_sessions_collection()
        res = col.delete_one({"session_id": session_id})
        if res.deleted_count == 0:
            raise HTTPException(404, {"code": "session_not_found", "message": f"Session {session_id} not found"})
        return {"session_id": session_id, "deleted": True}
    except HTTPException:
        raise
    except PyMongoError as exc:
        log.error("MongoDB delete failure for session %s: %s", session_id, exc)
        raise HTTPException(
            503, {"code": "session_store_unavailable", "message": f"MongoDB error: {type(exc).__name__}"}
        ) from exc
