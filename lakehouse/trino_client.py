"""Thin Trino DB-API wrapper that records real execution statistics."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import trino

from common.settings import Settings, get_settings


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    elapsed_ms: float
    query_id: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, r)) for r in self.rows]


def connect(settings: Settings | None = None, timeout_s: int | None = None,
            session_properties: dict[str, str] | None = None) -> trino.dbapi.Connection:
    s = settings or get_settings()
    timeout = timeout_s or s.trino_query_timeout_s
    return trino.dbapi.connect(
        host=s.trino_host,
        port=s.trino_port,
        user=s.trino_user,
        catalog=s.trino_catalog,
        schema=s.trino_schema,
        http_scheme="http",
        timezone="UTC",  # event_date is a UTC date; current_date must agree
        request_timeout=timeout + 15,
        session_properties={"query_max_execution_time": f"{timeout}s", **(session_properties or {})},
    )


def jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return v


def run_query(sql: str, params: list[Any] | None = None, max_rows: int | None = 10_000,
              conn: trino.dbapi.Connection | None = None, settings: Settings | None = None) -> QueryResult:
    own = conn is None
    conn = conn or connect(settings)
    try:
        cur = conn.cursor()
        t0 = time.perf_counter()
        cur.execute(sql, params) if params else cur.execute(sql)
        rows: list[list[Any]] = []
        truncated = False
        while True:
            batch = cur.fetchmany(1000)
            if not batch:
                break
            for r in batch:
                if max_rows is not None and len(rows) >= max_rows:
                    truncated = True
                    break
                rows.append([jsonable(v) for v in r])
            if truncated:
                cur.cancel()
                break
        elapsed = (time.perf_counter() - t0) * 1000
        columns = [d[0] for d in (cur.description or [])]
        raw = getattr(cur, "stats", None) or {}
        stats = {k: raw.get(k) for k in ("state", "elapsedTimeMillis", "cpuTimeMillis", "wallTimeMillis",
                                          "processedRows", "processedBytes", "physicalInputBytes",
                                          "peakMemoryBytes", "totalSplits") if k in raw}
        return QueryResult(columns, rows, round(elapsed, 1), getattr(cur, "query_id", None), stats, truncated)
    finally:
        if own:
            conn.close()


def wait_for_trino(timeout_s: float = 180, settings: Settings | None = None) -> None:
    deadline = time.time() + timeout_s
    last: Exception | None = None
    while time.time() < deadline:
        try:
            run_query("SELECT 1", settings=settings)
            return
        except Exception as exc:  # trino starting / not reachable yet
            last = exc
            time.sleep(3)
    raise TimeoutError(f"Trino not ready after {timeout_s}s: {last}")
