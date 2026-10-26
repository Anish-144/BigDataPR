"""AgentShield FastAPI application."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app import db, mongo
from backend.app.routers import (
    agents,
    analytics,
    anomalies,
    cases,
    health,
    investigations,
    reports,
    runs,
    security,
    test_runs,
)
from backend.app.services.test_runner import manager as test_run_manager

log = logging.getLogger("agentshield.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="AgentShield API",
    version="0.1.0",
    description="AI-agent benchmarking, evaluation, anomaly detection and security governance over a Kafka -> Spark -> "
    "Iceberg -> Trino lakehouse. All analytics are computed from lakehouse data; estimated costs and model-judged "
    "scores are labelled as such.",
)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - t0) * 1000:.1f}"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "invalid request",
                                                            "details": jsonable_encoder(exc.errors(), custom_encoder={Exception: str})}})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"[:500]}})


@app.on_event("startup")
def startup() -> None:
    try:
        db.init_db()
        recovered = test_run_manager.recover_orphans()
        if recovered:
            log.warning("marked %d orphaned test run(s) as failed", recovered)
    except Exception as exc:  # degraded mode: API still serves lakehouse analytics
        log.error("postgres unavailable at startup: %s", exc)

    try:
        mongo.init_mongo()
    except Exception as exc:  # degraded mode: case management handles unavailable store
        log.error("mongodb unavailable at startup: %s", exc)


app.include_router(health.router)
app.include_router(analytics.router)
app.include_router(runs.router)
app.include_router(agents.router)
app.include_router(test_runs.router)
app.include_router(anomalies.router)
app.include_router(security.router)
app.include_router(reports.router)
app.include_router(investigations.router)
app.include_router(cases.router)
