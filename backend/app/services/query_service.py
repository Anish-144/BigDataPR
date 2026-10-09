"""Safe analytics query service.

The API never executes caller-supplied SQL. It runs only *named* statements
from the curated catalog in ``sql/*.sql`` (read-only SELECT / WITH / EXPLAIN),
with parameters validated against the types of each query's declared defaults
and bound as prepared-statement parameters. Results are row-limited and the
Trino session has a query timeout.
"""

from __future__ import annotations

import re
import threading
import time
from functools import lru_cache
from typing import Any

from fastapi import HTTPException

from lakehouse.sql_catalog import SqlStatement, load_catalog
from lakehouse.trino_client import run_query

READ_ONLY = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)
SAFE_STRING = re.compile(r"^[A-Za-z0-9_.:@\-]{1,80}$")
MAX_ROWS = 5000
_CACHE_TTL_S = 15.0
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


@lru_cache(maxsize=1)
def catalog() -> dict[str, SqlStatement]:
    return {n: s for n, s in load_catalog().items() if READ_ONLY.match(s.sql)}


def validate_params(st: SqlStatement, raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if key not in st.defaults:
            raise HTTPException(422, {"code": "unknown_parameter", "message": f"{st.name} has no parameter '{key}'",
                                      "allowed": sorted(st.defaults)})
        default = st.defaults[key]
        try:
            if isinstance(default, int):
                v = int(value)
                if not 0 <= v <= 3650:
                    raise ValueError("out of range 0..3650")
            elif isinstance(default, float):
                v = float(value)
            else:
                v = str(value)
                if not SAFE_STRING.match(v):
                    raise ValueError("only [A-Za-z0-9_.:@-], max 80 chars")
        except ValueError as exc:
            raise HTTPException(422, {"code": "invalid_parameter", "message": f"{key}: {exc}"}) from exc
        out[key] = v
    return out


def run_named(name: str, params: dict[str, Any] | None = None, max_rows: int = MAX_ROWS, use_cache: bool = True) -> dict:
    st = catalog().get(name)
    if st is None:
        raise HTTPException(404, {"code": "unknown_query", "message": f"no catalog query named '{name}'"})
    clean = validate_params(st, params or {})
    key = (name, tuple(sorted(clean.items())), max_rows)
    now = time.time()
    if use_cache:
        with _lock:
            hit = _cache.get(key)
            if hit and now - hit[0] < _CACHE_TTL_S:
                return {**hit[1], "cached": True}
    sql, bound = st.bind(clean)
    try:
        res = run_query(sql, bound or None, max_rows=max_rows)
    except Exception as exc:
        raise HTTPException(503, {"code": "lakehouse_query_failed", "message": str(exc)[:500], "query": name}) from exc
    payload = {
        "name": name,
        "title": st.tags.get("title"),
        "params": {**st.defaults, **clean},
        "columns": res.columns,
        "rows": res.as_dicts(),
        "row_count": len(res.rows),
        "truncated": res.truncated,
        "elapsed_ms": res.elapsed_ms,
        "trino_stats": res.stats,
        "query_id": res.query_id,
        "cached": False,
    }
    with _lock:
        _cache[key] = (now, payload)
    return payload


def describe(st: SqlStatement) -> dict:
    return {
        "name": st.name,
        "file": st.file,
        "title": st.tags.get("title"),
        "concept": st.tags.get("concept"),
        "question": st.tags.get("question"),
        "interpretation": st.tags.get("interpretation"),
        "params": st.defaults,
        "sql": st.sql,
    }


def sql_scalar(sql: str, params: list | None = None) -> Any:
    """For fixed, server-side SQL strings only (never caller-supplied text)."""
    try:
        return run_query(sql, params).rows[0][0]
    except Exception as exc:
        raise HTTPException(503, {"code": "lakehouse_query_failed", "message": str(exc)[:500]}) from exc


def sql_rows(sql: str, params: list | None = None, max_rows: int = MAX_ROWS) -> list[dict]:
    """For fixed, server-side SQL strings only (never caller-supplied text)."""
    try:
        return run_query(sql, params, max_rows=max_rows).as_dicts()
    except Exception as exc:
        raise HTTPException(503, {"code": "lakehouse_query_failed", "message": str(exc)[:500]}) from exc
