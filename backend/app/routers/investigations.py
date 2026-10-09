"""AI investigation assistant API (evidence-grounded; optional LLM rephrasing)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app import db
from common import llm
from investigation import answer_service as svc
from investigation.retrieval import retriever

router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])


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


@router.post("")
def investigate(body: InvestigationIn) -> dict:
    """Answer an investigation question from lakehouse evidence and local runbooks.
    Evidence is gathered only through fixed, parameterised queries; no SQL is generated from the question."""
    try:
        ans = svc.investigate(body.question, svc.Context(**body.context.model_dump()), use_llm=body.use_llm)
    except Exception as exc:
        raise HTTPException(503, {"code": "investigation_failed", "message": f"{type(exc).__name__}: {exc}"[:500]}) from exc
    out = ans.to_dict()
    try:
        with db.session_factory()() as s:
            s.add(db.InvestigationLog(question=body.question, intent=ans.intent, answer=ans.answer,
                                      evidence=out["evidence"], mode=ans.mode))
            s.commit()
    except Exception:
        out["warning"] = "investigation history not saved (operational database unavailable)"
    return out


@router.get("/examples")
def examples() -> dict:
    return {"examples": svc.EXAMPLES, "llm_enabled": llm.llm_enabled(),
            "llm_model": llm.model_name() if llm.llm_enabled() else None,
            "retrieval_backend": retriever().backend}


@router.get("/history")
def history(limit: int = Query(20, ge=1, le=200)) -> dict:
    try:
        with db.session_factory()() as s:
            rows = s.scalars(select(db.InvestigationLog).order_by(db.InvestigationLog.created_at.desc()).limit(limit)).all()
    except Exception as exc:
        raise HTTPException(503, {"code": "history_unavailable", "message": str(exc)[:300]}) from exc
    return {"items": [{"id": r.id, "question": r.question, "intent": r.intent, "mode": r.mode, "answer": r.answer,
                       "evidence": r.evidence, "created_at": r.created_at.isoformat()} for r in rows]}
