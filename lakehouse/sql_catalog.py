"""Parser for the annotated SQL files in ``sql/``.

Each statement may be preceded by a comment block with tags::

    -- @query: p95_latency_by_version
    -- @title: p95 latency by agent version
    -- @concept: Percentiles, GROUP BY
    -- @question: Which agent versions have the slowest tail latency?
    -- @interpretation: ...
    -- @params: days=30
    SELECT ... WHERE event_date >= current_date - (:days * INTERVAL '1' DAY);

``:name`` placeholders are converted to ``?`` and bound as *prepared-statement
parameters* (never string-concatenated). Statements without ``@query`` are
setup/DDL statements executed in file order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.settings import REPO_ROOT

SQL_DIR = REPO_ROOT / "sql"
_TAG = re.compile(r"^\s*--\s*@(\w+)\s*:\s*(.*)$")
_PARAM = re.compile(r"(?<![:\w]):([a-z_][a-z0-9_]*)")


@dataclass
class SqlStatement:
    file: str
    index: int
    sql: str
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str | None:
        return self.tags.get("query")

    @property
    def defaults(self) -> dict[str, Any]:
        raw = self.tags.get("params", "").strip()
        out: dict[str, Any] = {}
        if not raw:
            return out
        for part in raw.split(","):
            k, _, v = part.strip().partition("=")
            out[k.strip()] = coerce(v.strip())
        return out

    def bind(self, overrides: dict[str, Any] | None = None) -> tuple[str, list[Any]]:
        """Return (sql_with_qmarks, ordered_params). Unknown parameters raise ValueError."""
        values = {**self.defaults, **(overrides or {})}
        unknown = set(overrides or {}) - set(self.defaults)
        if unknown:
            raise ValueError(f"unknown parameter(s) for {self.name}: {sorted(unknown)}")
        params: list[Any] = []

        def repl(segment: str) -> str:
            def sub(m: re.Match[str]) -> str:
                key = m.group(1)
                if key not in values:
                    raise ValueError(f"missing value for parameter :{key}")
                params.append(values[key])
                return "?"

            return _PARAM.sub(sub, segment)

        return _map_code_segments(self.sql, repl), params


def coerce(v: str) -> Any:
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d*", v):
        return float(v)
    return v.strip("'\"")


def _map_code_segments(sql: str, fn) -> str:
    """Apply ``fn`` to SQL text outside string literals and quoted identifiers."""
    out, buf, i, n = [], [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            out.append(fn("".join(buf)))
            buf = []
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # escaped quote
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
            continue
        buf.append(ch)
        i += 1
    out.append(fn("".join(buf)))
    return "".join(out)


def split_statements(text: str) -> list[tuple[list[str], str]]:
    """Split SQL text into (leading_comment_lines, statement_sql) at top-level semicolons."""
    statements: list[tuple[list[str], str]] = []
    buf: list[str] = []
    i, n = 0, len(text)
    in_str = None
    while i < n:
        ch = text[i]
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_str = ch
            buf.append(ch)
            i += 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            buf.append(text[i:j])
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            buf.append(text[i:j])
            i = j
            continue
        if ch == ";":
            statements.append(_finish("".join(buf)))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf)
    if tail.strip() and any(not l.strip().startswith("--") for l in tail.strip().splitlines() if l.strip()):
        statements.append(_finish(tail))
    return [s for s in statements if s[1].strip()]


def _finish(chunk: str) -> tuple[list[str], str]:
    lines = chunk.strip("\n").splitlines()
    comments: list[str] = []
    body_start = 0
    for idx, line in enumerate(lines):
        if line.strip().startswith("--") or not line.strip():
            comments.append(line)
            body_start = idx + 1
        else:
            break
    body = "\n".join(lines[body_start:]).strip()
    return comments, body


def load_file(path: str | Path) -> list[SqlStatement]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    out: list[SqlStatement] = []
    for idx, (comments, body) in enumerate(split_statements(text)):
        tags: dict[str, str] = {}
        last_key = None
        for line in comments:
            m = _TAG.match(line)
            if m:
                last_key = m.group(1)
                tags[last_key] = m.group(2).strip()
            elif last_key and line.strip().startswith("--") and line.strip() != "--" and not line.strip().startswith("-- ="):
                cont = line.strip()[2:].strip()
                if cont.startswith("@"):
                    last_key = None
                elif cont and last_key in ("interpretation", "question", "notes"):
                    tags[last_key] += " " + cont
            else:
                last_key = None
        out.append(SqlStatement(file=path.name, index=idx, sql=body, tags=tags))
    return out


def load_catalog(sql_dir: Path = SQL_DIR) -> dict[str, SqlStatement]:
    """All named queries across sql/*.sql keyed by @query name."""
    catalog: dict[str, SqlStatement] = {}
    for path in sorted(sql_dir.glob("*.sql")):
        for st in load_file(path):
            if st.name:
                if st.name in catalog:
                    raise ValueError(f"duplicate @query name {st.name} in {path.name}")
                catalog[st.name] = st
    return catalog
