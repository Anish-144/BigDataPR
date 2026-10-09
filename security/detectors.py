"""Content detectors: prompt-injection indicators, synthetic sensitive-data
patterns, and exfiltration-like action sequences.

These are heuristics. A match is a *finding* to investigate, not proof of an
attack. Matched secrets are redacted before they are stored as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

from common.config import load_policy


@lru_cache(maxsize=1)
def _injection_patterns() -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in load_policy()["prompt_injection_indicators"])


@lru_cache(maxsize=1)
def _sensitive_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((p["name"], re.compile(p["regex"])) for p in load_policy()["sensitive_patterns"])


def redact(value: str, keep: int = 6) -> str:
    return value[:keep] + "*" * max(4, len(value) - keep)


def find_prompt_injection(text: str) -> list[str]:
    """Return the indicator patterns matched by ``text`` (empty list if none)."""
    return [p.pattern for p in _injection_patterns() if p.search(text)]


def find_sensitive_data(text: str) -> list[tuple[str, str]]:
    """Return ``(pattern_name, redacted_match)`` for every synthetic secret in ``text``."""
    hits: list[tuple[str, str]] = []
    for name, pattern in _sensitive_patterns():
        hits.extend((name, redact(m.group(0))) for m in pattern.finditer(text))
    return hits


def redact_text(text: str) -> str:
    for _, pattern in _sensitive_patterns():
        text = pattern.sub(lambda m: redact(m.group(0)), text)
    return text


@dataclass(frozen=True)
class Action:
    kind: str  # "read" | "tool"
    name: str  # doc id / resource / tool name
    sensitive: bool = False


def detect_exfiltration(actions: Iterable[Action], egress_tools: set[str]) -> tuple[str, str] | None:
    """Sensitive read followed later by an egress tool call in the same trace.

    Returns ``(sensitive_source, egress_tool)`` for the first such pair, else None.
    """
    sensitive_source: str | None = None
    for a in actions:
        if a.kind == "read" and a.sensitive and sensitive_source is None:
            sensitive_source = a.name
        elif a.kind == "tool" and a.name in egress_tools and sensitive_source is not None:
            return sensitive_source, a.name
    return None


def summarize_findings(findings: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.category] = out.get(f.category, 0) + 1
    return out
