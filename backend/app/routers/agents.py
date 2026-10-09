"""Agent registry: config-defined agents (dimension) + operational records in Postgres."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.app import db
from common.config import load_agent_catalog, load_policy

router = APIRouter(prefix="/api/v1", tags=["agents"])


class AgentIn(BaseModel):
    agent_id: str = Field(pattern=r"^[a-z0-9\-]{3,64}$")
    agent_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    agent_name: str = Field(min_length=3, max_length=128)
    workload_type: str = Field(pattern=r"^(qa|rag|tool|multi_step)$")
    model_name: str = Field(pattern=r"^[A-Za-z0-9_.\-]{2,64}$")
    prompt_version: str = Field(pattern=r"^[A-Za-z0-9_.\-]{2,64}$")
    release_seq: int = Field(ge=1, le=10000)
    profile: dict[str, Any] = Field(default_factory=dict)


def _config_agents() -> list[dict]:
    policy = load_policy()["agents"]
    out = []
    for a in load_agent_catalog():
        for v in a["versions"]:
            out.append({
                "agent_id": a["agent_id"], "agent_name": a["agent_name"], "workload_type": a["workload_type"],
                "description": a.get("description"), "agent_version": v["version"], "release_seq": v["release_seq"],
                "released_at": str(v["released_at"]), "model_name": v["model_name"], "prompt_version": v["prompt_version"],
                "profile": v["profile"], "policy": policy.get(a["agent_id"]), "source": "config",
            })
    return out


@router.get("/agents")
def list_agents() -> dict:
    agents = _config_agents()
    try:
        with db.session_factory()() as s:
            for r in s.scalars(select(db.AgentRecord)).all():
                agents.append({"agent_id": r.agent_id, "agent_name": r.agent_name, "workload_type": r.workload_type,
                               "agent_version": r.agent_version, "release_seq": r.release_seq, "model_name": r.model_name,
                               "prompt_version": r.prompt_version, "profile": r.profile, "source": "api",
                               "created_at": r.created_at.isoformat()})
    except Exception as exc:  # degraded: config agents still listed
        return {"agents": agents, "warning": f"operational registry unavailable: {type(exc).__name__}"}
    return {"agents": agents}


@router.post("/agents", status_code=201)
def register_agent(body: AgentIn) -> dict:
    """Register an agent version in the operational registry (Postgres). Config agents are read-only."""
    if any(a["agent_id"] == body.agent_id and a["agent_version"] == body.agent_version for a in _config_agents()):
        raise HTTPException(409, {"code": "exists_in_config", "message": "this version is defined in config/agents.yaml"})
    with db.session_factory()() as s:
        dup = s.scalars(select(db.AgentRecord).where(db.AgentRecord.agent_id == body.agent_id,
                                                     db.AgentRecord.agent_version == body.agent_version)).first()
        if dup:
            raise HTTPException(409, {"code": "already_registered", "message": "agent version already registered"})
        rec = db.AgentRecord(**body.model_dump(), source="api")
        s.add(rec)
        s.commit()
        return {"id": rec.id, **body.model_dump(), "source": "api",
                "note": "Registered for tracking. Only config-defined agents have mock-agent behaviour profiles in the test lab."}
