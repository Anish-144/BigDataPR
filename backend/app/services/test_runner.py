"""Background execution of test runs triggered from the API.

A test run executes the same code path as the CLI (generator.producer.run_test)
in a background thread, which spawns the generator worker processes. Status
and progress are persisted in PostgreSQL (operational store); the telemetry
itself flows through Kafka into the lakehouse like any other run.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update

from backend.app import db
from common import ids
from common.settings import get_settings
from generator.runner import TestRunConfig

log = logging.getLogger("agentshield.test_runner")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_TEST_RUNS", "1"))


class TestRunManager:
    __test__ = False

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stops: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    def active(self) -> list[str]:
        with self._lock:
            return [k for k, t in self._threads.items() if t.is_alive()]

    def recover_orphans(self) -> int:
        """Runs left 'queued'/'running' by a previous API process can no longer progress."""
        with db.session_factory()() as s:
            res = s.execute(update(db.TestRunRecord)
                            .where(db.TestRunRecord.status.in_(["queued", "running"]))
                            .values(status="failed", error="interrupted: API process restarted"))
            s.commit()
            return res.rowcount or 0

    def start(self, cfg: TestRunConfig) -> str:
        if len(self.active()) >= MAX_CONCURRENT:
            raise HTTPException(409, {"code": "test_run_in_progress",
                                      "message": f"at most {MAX_CONCURRENT} concurrent test run(s); stop or wait",
                                      "active": self.active()})
        now = datetime.now(timezone.utc)
        test_run_id = ids.test_run_id(now.strftime("%Y%m%d"), random.Random(uuid.uuid4().int))
        with db.session_factory()() as s:
            s.add(db.TestRunRecord(test_run_id=test_run_id, name=cfg.name, status="queued",
                                   config=cfg.model_dump(mode="json")))
            s.commit()
        stop = threading.Event()
        thread = threading.Thread(target=self._run, args=(test_run_id, cfg, stop), name=f"testrun-{test_run_id}", daemon=True)
        with self._lock:
            self._stops[test_run_id] = stop
            self._threads[test_run_id] = thread
        thread.start()
        return test_run_id

    def stop(self, test_run_id: str) -> bool:
        with self._lock:
            ev = self._stops.get(test_run_id)
            alive = test_run_id in self._threads and self._threads[test_run_id].is_alive()
        with db.session_factory()() as s:
            s.execute(update(db.TestRunRecord).where(db.TestRunRecord.test_run_id == test_run_id)
                      .values(stop_requested=True))
            s.commit()
        if ev is None or not alive:
            return False
        ev.set()
        return True

    def _set(self, test_run_id: str, **values: Any) -> None:
        with db.session_factory()() as s:
            s.execute(update(db.TestRunRecord).where(db.TestRunRecord.test_run_id == test_run_id).values(**values))
            s.commit()

    def _run(self, test_run_id: str, cfg: TestRunConfig, stop: threading.Event) -> None:
        from generator.producer import run_test  # heavy import, only in the worker thread

        self._set(test_run_id, status="running")
        last = [0.0]

        def progress(n: int) -> None:
            if time.time() - last[0] >= 2:
                last[0] = time.time()
                self._set(test_run_id, progress_tasks=int(n))

        try:
            summary = run_test(cfg, "kafka", get_settings().kafka_bootstrap, test_run_id,
                               should_stop=stop.is_set, on_progress=progress)
            summary.pop("workers_detail", None)
            self._set(test_run_id, status=summary["status"], progress_tasks=summary["tasks_completed"], summary=summary)
            log.info("test run %s finished: %s", test_run_id, summary["status"])
        except Exception as exc:  # recorded, never swallowed silently
            log.exception("test run %s failed", test_run_id)
            self._set(test_run_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:2000])


manager = TestRunManager()


def get_record(test_run_id: str) -> dict | None:
    with db.session_factory()() as s:
        r = s.scalars(select(db.TestRunRecord).where(db.TestRunRecord.test_run_id == test_run_id)).first()
        if r is None:
            return None
        return {"test_run_id": r.test_run_id, "name": r.name, "status": r.status, "config": r.config,
                "progress_tasks": r.progress_tasks, "summary": r.summary, "error": r.error,
                "stop_requested": r.stop_requested, "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def list_records(limit: int = 100) -> list[dict]:
    with db.session_factory()() as s:
        rows = s.scalars(select(db.TestRunRecord).order_by(db.TestRunRecord.created_at.desc()).limit(limit)).all()
        return [{"test_run_id": r.test_run_id, "name": r.name, "status": r.status, "progress_tasks": r.progress_tasks,
                 "requested_tasks": (r.config or {}).get("tasks"), "error": r.error,
                 "created_at": r.created_at.isoformat()} for r in rows]
