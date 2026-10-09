from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from generator import event_schema as es
from ingestion.validation import DIRTY_KINDS, DirtyDataInjector, route_raw_event

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def span_event(**over) -> es.SpanEvent:
    payload = dict(span_id="a" * 16, span_kind="llm_call", span_name="x", start_time=NOW, end_time=NOW,
                   duration_ms=12.5, status="ok", step_index=0)
    payload.update(over.pop("payload", {}))
    base = dict(event_id="evt-00000001", event_time=NOW, producer="test", test_run_id="TR-1", run_id="R-1",
                trace_id="b" * 32, agent_id="qa-assistant", agent_version="1.0.0", payload=es.SpanPayload(**payload))
    base.update(over)
    return es.SpanEvent(**base)


def test_round_trip_and_routing():
    e = span_event()
    parsed = es.parse_event(e.to_json())
    assert isinstance(parsed, es.SpanEvent)
    assert parsed.topic == es.Topic.TRACES
    assert parsed.kafka_key() == "b" * 32


@pytest.mark.parametrize("bad", [
    {"event_time": datetime(2026, 1, 1)},             # naive timestamp
    {"trace_id": "XYZ"},                               # not 32-hex
    {"schema_version": "9.9"},                         # unsupported version
    {"event_id": "short"},                             # too short
])
def test_envelope_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        span_event(**bad)


def test_payload_rejects_unknown_fields_and_bad_enums():
    with pytest.raises(ValidationError):
        span_event(payload={"status": "exploded"})
    raw = json.loads(span_event().to_json())
    raw["payload"]["surprise"] = 1
    with pytest.raises(ValidationError):
        es.parse_event(json.dumps(raw))


def test_required_context_enforced():
    raw = json.loads(span_event().to_json())
    raw["run_id"] = None
    with pytest.raises(ValueError, match="missing required context"):
        es.parse_event(json.dumps(raw))


def test_route_raw_event_valid_and_dead_letter():
    routed, ok = route_raw_event(span_event().to_json())
    assert ok and routed.topic == "agent-traces"
    routed, ok = route_raw_event('{"event_type": "span.completed"')
    assert not ok and routed.topic == "agent-events-dlq"
    assert json.loads(routed.value)["reason"].startswith("contract_validation_failed")


def test_dirty_injector_counts_every_corruption():
    inj = DirtyDataInjector(rate=1.0, seed=1)
    value = span_event().to_json().encode()
    produced = 0
    for _ in range(400):
        produced += len(inj.apply("span.completed", value))
    assert set(inj.injected) == set(DIRTY_KINDS)
    assert sum(inj.injected.values()) == 400
    assert produced == 400 + inj.injected["duplicate"]


def test_dirty_injector_structural_kinds_fail_contract():
    inj = DirtyDataInjector(rate=1.0, seed=3)
    value = span_event().to_json().encode()
    for _ in range(200):
        before = dict(inj.injected)
        out = inj.apply("span.completed", value)
        kind = next(k for k in inj.injected if inj.injected[k] != before.get(k, 0))
        if kind in ("malformed_json", "missing_event_id", "unknown_event_type", "bad_timestamp"):
            _, ok = route_raw_event(out[0])
            assert not ok, kind
