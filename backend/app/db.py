"""Operational PostgreSQL store (SQLAlchemy 2.0): agent registry, test-run
requests, alert feedback, investigation log. Analytical data lives in the
lakehouse; this database only holds mutable application state."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from common.settings import get_settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AgentRecord(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_version: Mapped[str] = mapped_column(String(32))
    agent_name: Mapped[str] = mapped_column(String(128))
    workload_type: Mapped[str] = mapped_column(String(32))
    model_name: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    release_seq: Mapped[int] = mapped_column(Integer)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(16), default="config")  # config | api
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TestRunRecord(Base):
    __tablename__ = "test_runs"
    test_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))  # queued | running | completed | stopped | failed
    config: Mapped[dict] = mapped_column(JSON)
    progress_tasks: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AlertFeedback(Base):
    __tablename__ = "alert_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(16))  # useful | noisy | acknowledged
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer: Mapped[str] = mapped_column(String(64), default="analyst")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class InvestigationLog(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(64))
    answer: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(32))  # deterministic | llm
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


@lru_cache(maxsize=1)
def engine() -> Engine:
    return create_engine(
        get_settings().postgres_dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 3},
    )


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker:
    return sessionmaker(bind=engine(), expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine())
