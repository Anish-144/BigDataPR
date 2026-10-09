"""Deterministic identifier helpers.

All IDs for a task are derived from a per-task ``random.Random`` seeded from
(test-run seed, task index). The same seed therefore reproduces identical
run/trace/span/event IDs regardless of how many workers execute the tasks.
"""

from __future__ import annotations

import hashlib
import random
import uuid


def task_rng(seed: int, task_index: int, salt: str = "") -> random.Random:
    digest = hashlib.blake2b(f"{seed}:{task_index}:{salt}".encode(), digest_size=8).digest()
    return random.Random(int.from_bytes(digest, "big"))


def event_id(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def trace_id(rng: random.Random) -> str:
    return f"{rng.getrandbits(128):032x}"


def span_id(rng: random.Random) -> str:
    return f"{rng.getrandbits(64):016x}"


def short_hex(rng: random.Random, n: int = 6) -> str:
    return f"{rng.getrandbits(4 * n):0{n}x}"


def test_run_id(date_str: str, rng: random.Random) -> str:
    """``TR-YYYYMMDD-xxxxxx``"""
    return f"TR-{date_str}-{short_hex(rng)}"


def run_id(test_run_id_: str, seq: int) -> str:
    """``R-<test-run-hex>-<seq>`` - unique because seq is unique inside a test run."""
    return f"R-{test_run_id_.rsplit('-', 1)[-1]}-{seq:06d}"


def stable_id(*parts: object, prefix: str = "", n: int = 16) -> str:
    digest = hashlib.blake2b(":".join(str(p) for p in parts).encode(), digest_size=n // 2).hexdigest()
    return f"{prefix}{digest}"


def scoped(test_run_id: str, value: str) -> str:
    """Make a simulation-derived hex id unique to its test run (same length, deterministic).

    The workload and its outcomes depend only on (seed, task index); identifiers additionally depend on
    the test_run_id so that re-running a scenario with the same seed never reuses trace/span/event ids.
    """
    return hashlib.blake2b(f"{test_run_id}:{value}".encode(), digest_size=len(value) // 2).hexdigest()


def scoped_event_id(test_run_id: str, value: str) -> str:
    digest = hashlib.blake2b(f"{test_run_id}:{value}".encode(), digest_size=16).digest()
    return str(uuid.UUID(bytes=digest, version=4))
