"""Producer-side validation, routing and dead-letter handling.

* ``route_raw_event`` validates an untrusted raw JSON event against the shared
  contract and returns either a (topic, key, value) routing decision or a
  dead-letter record for ``agent-events-dlq``.
* ``DirtyDataInjector`` deliberately corrupts a configurable fraction of
  *already validated* events, emulating a buggy upstream producer, so the
  stream processor's quarantine logic and the data-quality SQL can be tested
  against known ground truth.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

from generator.event_schema import EVENT_TOPIC, EventType, Topic, parse_event

DIRTY_KINDS = (
    "malformed_json",       # structural -> quarantined by Spark
    "missing_event_id",     # structural -> quarantined by Spark
    "unknown_event_type",   # structural -> quarantined by Spark
    "bad_timestamp",        # structural -> quarantined by Spark
    "negative_duration",    # semantic -> kept, flagged by data-quality SQL
    "orphan_parent",        # semantic -> kept, flagged by data-quality SQL
    "duplicate",            # semantic -> kept, flagged by data-quality SQL
)
SPAN_ONLY_KINDS = frozenset({"negative_duration", "orphan_parent"})
STRUCTURAL_KINDS = ("malformed_json", "missing_event_id", "unknown_event_type", "bad_timestamp")
SEMANTIC_KINDS = ("negative_duration", "orphan_parent", "duplicate")


@dataclass(frozen=True)
class Routed:
    topic: str
    key: bytes
    value: bytes


def dead_letter(raw: bytes | str, reason: str, source: str) -> Routed:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    record = {
        "reason": reason[:500],
        "source": source,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "raw": text[:20000],
    }
    return Routed(Topic.DLQ.value, b"dlq", json.dumps(record).encode())


def route_raw_event(raw: bytes | str, source: str = "api") -> tuple[Routed, bool]:
    """Validate and route one raw event. Returns (routed, is_valid)."""
    try:
        event = parse_event(raw)
    except (ValidationError, ValueError) as exc:
        return dead_letter(raw, f"contract_validation_failed: {exc}", source), False
    topic = EVENT_TOPIC[EventType(event.event_type)].value
    value = raw.encode() if isinstance(raw, str) else raw
    return Routed(topic, event.kafka_key().encode(), value), True


class DirtyDataInjector:
    def __init__(self, rate: float, seed: int, kinds: tuple[str, ...] | list[str] | None = None):
        self.rate = rate
        self.rng = random.Random(seed)
        self.kinds = tuple(kinds) if kinds else DIRTY_KINDS
        unknown = set(self.kinds) - set(DIRTY_KINDS)
        if unknown:
            raise ValueError(f"unknown dirty kinds: {sorted(unknown)}")
        self.injected: Counter[str] = Counter()

    def apply(self, event_type: str, value: bytes) -> list[bytes]:
        """Return the list of payloads to send for this event (usually [value])."""
        if self.rate <= 0 or self.rng.random() >= self.rate:
            return [value]
        kinds = [k for k in self.kinds if event_type == "span.completed" or k not in SPAN_ONLY_KINDS]
        if not kinds:
            return [value]
        kind = self.rng.choice(kinds)
        self.injected[kind] += 1
        if kind == "duplicate":
            return [value, value]
        if kind == "malformed_json":
            # Keep the envelope prefix (ids) so the record stays attributable in the DLQ.
            return [value[: min(len(value) - 2, max(300, len(value) // 3))]]
        obj = json.loads(value)
        if kind == "missing_event_id":
            obj.pop("event_id", None)
        elif kind == "unknown_event_type":
            obj["event_type"] = "span.mystery"
        elif kind == "bad_timestamp":
            obj["event_time"] = "yesterday-ish"
        elif kind == "negative_duration":
            obj["payload"]["duration_ms"] = -abs(obj["payload"]["duration_ms"]) - 1.0
        elif kind == "orphan_parent":
            obj["payload"]["parent_span_id"] = f"{self.rng.getrandbits(64):016x}"
        return [json.dumps(obj, separators=(",", ":")).encode()]
