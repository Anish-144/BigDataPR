from __future__ import annotations

from fastapi import APIRouter

from backend.app import db
from backend.app.services.pipeline_health import pipeline_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness of the API process itself (dependencies: see /api/v1/pipeline/health)."""
    return {"status": "ok", "service": "agentshield-api"}


@router.get("/api/v1/pipeline/health")
def get_pipeline_health() -> dict:
    """Measured status of Kafka, Spark, Trino/lakehouse, PostgreSQL and (optional) Airflow."""
    return pipeline_health(db.engine())
