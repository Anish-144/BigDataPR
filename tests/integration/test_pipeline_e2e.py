"""End-to-end pipeline test against the running Docker stack:
generator -> Kafka -> Spark Structured Streaming -> Iceberg/MinIO -> Trino.

Run with:  pytest -m integration tests/integration
Requires:  docker compose up -d (Kafka on localhost:9094, Trino on localhost:8080).

The generator's own summary (events by type, injected dirty records by kind)
is the ground truth; the lakehouse must match it exactly.
"""

from __future__ import annotations

import time

import pytest

from generator.producer import run_test
from generator.runner import TestRunConfig
from ingestion.validation import SEMANTIC_KINDS, STRUCTURAL_KINDS
from lakehouse.trino_client import run_query

pytestmark = pytest.mark.integration

MIX = [{"agent_id": a, "version": v, "weight": 1} for a, v in (
    ("qa-assistant", "1.1.0"), ("rag-helpdesk", "2.1.0"), ("ops-tool-agent", "1.1.0"), ("planner-agent", "2.0.0"))]
T = "lakehouse.analytics"


def _stack_available() -> bool:
    try:
        run_query("SELECT 1")
        from confluent_kafka.admin import AdminClient

        AdminClient({"bootstrap.servers": "127.0.0.1:9094", "socket.timeout.ms": 3000}).list_topics(timeout=5)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def require_stack():
    if not _stack_available():
        pytest.skip("Docker stack not reachable (start it with `docker compose up -d`)")


def scalar(sql: str, params: list | None = None):
    return run_query(sql, params).rows[0][0]


def wait_for_rows(test_run_id: str, expected: int, timeout_s: float = 240) -> int:
    deadline = time.time() + timeout_s
    n = 0
    while time.time() < deadline:
        n = scalar(f"SELECT count(*) FROM {T}.raw_agent_events WHERE test_run_id = ? OR raw_value LIKE ?",
                   [test_run_id, f"%{test_run_id}%"])
        if n >= expected:
            # one more trigger interval so the test-run MERGE and batch metrics land too
            time.sleep(12)
            return n
        time.sleep(5)
    return n


@pytest.fixture(scope="module")
def clean_run():
    cfg = TestRunConfig(name="it_clean", seed=101, tasks=150, workers=2, sim_days=0.2, workload_mix=MIX,
                        fault_profile={"slow_tool": 0.05, "loop": 0.05, "policy_violation": 0.05, "prompt_injection": 0.05})
    summary = run_test(cfg, "kafka", "127.0.0.1:9094", write_results=False)
    assert summary["status"] == "completed" and summary["delivery"]["failed"] == 0
    wait_for_rows(summary["test_run_id"], summary["events_emitted"])
    return summary


def _dirty(name: str, seed: int, kinds: tuple[str, ...]) -> dict:
    cfg = TestRunConfig(name=name, seed=seed, tasks=200, workers=2, sim_days=0.2, workload_mix=MIX,
                        dirty_rate=0.05, dirty_kinds=list(kinds))
    summary = run_test(cfg, "kafka", "127.0.0.1:9094", write_results=False)
    assert sum(summary["dirty_injected"].values()) > 20
    wait_for_rows(summary["test_run_id"], summary["events_emitted"])
    return summary


@pytest.fixture(scope="module")
def dirty_run():
    """Structural corruption only -> must be quarantined with the right reason."""
    return _dirty("it_dirty_structural", 202, STRUCTURAL_KINDS)


@pytest.fixture(scope="module")
def semantic_run():
    """Semantic corruption only -> must be kept and be detectable by data-quality SQL."""
    return _dirty("it_dirty_semantic", 303, SEMANTIC_KINDS)


def test_clean_run_lands_completely(clean_run):
    tr, by_type = clean_run["test_run_id"], clean_run["events_by_type"]
    p = [tr]
    assert scalar(f"SELECT count(*) FROM {T}.raw_agent_events WHERE test_run_id = ?", p) == clean_run["events_emitted"]
    assert scalar(f"SELECT count_if(NOT is_valid) FROM {T}.raw_agent_events WHERE test_run_id = ?", p) == 0
    assert scalar(f"SELECT count(*) FROM {T}.agent_spans WHERE test_run_id = ?", p) == by_type["span.completed"]
    assert scalar(f"SELECT count(DISTINCT run_id) FROM {T}.agent_run_metrics WHERE test_run_id = ?", p) == 150
    assert scalar(f"SELECT count(*) FROM {T}.agent_evaluation_results WHERE test_run_id = ?", p) == by_type["evaluation.result"]
    assert scalar(f"SELECT count(*) FROM {T}.agent_security_findings WHERE test_run_id = ?", p) == by_type.get("security.finding", 0)


def test_clean_run_trace_integrity(clean_run):
    p = [clean_run["test_run_id"]]
    # exactly one root span per trace, and every parent_span_id resolves inside its trace
    bad_roots = scalar(f"""
        SELECT count(*) FROM (
            SELECT trace_id FROM {T}.agent_spans WHERE test_run_id = ?
            GROUP BY trace_id HAVING count_if(parent_span_id IS NULL) <> 1)""", p)
    assert bad_roots == 0
    orphans = scalar(f"""
        SELECT count(*) FROM {T}.agent_spans c
        LEFT JOIN {T}.agent_spans pa ON pa.trace_id = c.trace_id AND pa.span_id = c.parent_span_id
        WHERE c.test_run_id = ? AND c.parent_span_id IS NOT NULL AND pa.span_id IS NULL""", p)
    assert orphans == 0
    # run latency equals the root span duration
    mismatched = scalar(f"""
        SELECT count(*) FROM {T}.agent_run_metrics m
        JOIN {T}.agent_spans s ON s.trace_id = m.trace_id AND s.parent_span_id IS NULL
        WHERE m.test_run_id = ? AND abs(m.latency_ms - s.duration_ms) > 0.01""", p)
    assert mismatched == 0


def test_test_run_upserted_via_merge(clean_run):
    rows = run_query(f"SELECT status, total_runs, total_events FROM {T}.agent_test_runs WHERE test_run_id = ?",
                     [clean_run["test_run_id"]]).rows
    assert rows == [["completed", 150, clean_run["events_emitted"]]]


def test_dirty_records_quarantined_with_exact_reasons(dirty_run):
    tr, inj = dirty_run["test_run_id"], dirty_run["dirty_injected"]
    reasons = dict(run_query(f"""
        SELECT validation_error, count(*) FROM {T}.dead_letter_events
        WHERE raw_value LIKE ? GROUP BY 1""", [f"%{tr}%"]).rows)
    expected = {
        "malformed_json": inj.get("malformed_json", 0),
        "missing_event_id": inj.get("missing_event_id", 0),
        "unknown_event_type": inj.get("unknown_event_type", 0),
        "invalid_event_time": inj.get("bad_timestamp", 0),
    }
    assert reasons == {k: v for k, v in expected.items() if v}
    # bronze keeps every record, valid or not
    assert scalar(f"SELECT count(*) FROM {T}.raw_agent_events WHERE test_run_id = ? OR raw_value LIKE ?",
                  [tr, f"%{tr}%"]) == dirty_run["events_emitted"]


def test_semantic_issues_kept_and_detectable(semantic_run):
    tr, inj = semantic_run["test_run_id"], semantic_run["dirty_injected"]
    assert scalar(f"SELECT count_if(NOT is_valid) FROM {T}.raw_agent_events WHERE test_run_id = ?", [tr]) == 0
    p = [tr]
    dupes = scalar(f"""SELECT count(*) - count(DISTINCT event_id) FROM {T}.raw_agent_events
                       WHERE test_run_id = ? AND is_valid""", p)
    assert dupes == inj.get("duplicate", 0)
    neg = scalar(f"SELECT count_if(contains(dq_flags, 'negative_duration')) FROM {T}.agent_spans WHERE test_run_id = ?", p)
    assert neg == inj.get("negative_duration", 0)
    orphans = scalar(f"""
        SELECT count(DISTINCT c.event_id) FROM {T}.agent_spans c
        LEFT JOIN {T}.agent_spans pa ON pa.trace_id = c.trace_id AND pa.span_id = c.parent_span_id
        WHERE c.test_run_id = ? AND c.parent_span_id IS NOT NULL AND pa.span_id IS NULL""", p)
    assert orphans == inj.get("orphan_parent", 0)


def test_streaming_batch_metrics_recorded(clean_run):
    n = scalar(f"""SELECT count(*) FROM {T}.pipeline_batch_metrics
                   WHERE batch_end >= from_iso8601_timestamp(?) AND input_rows > 0""", [clean_run["started_at"]])
    assert n >= 1


def test_truncated_json_always_labelled_malformed():
    """Truncation can cut a record inside "payload" after a complete envelope. Spark's PERMISSIVE parser then
    returns partial results; the corrupt-record column must still classify every such record as malformed_json."""
    cfg = TestRunConfig(name="it_truncation", seed=404, tasks=1500, workers=2, sim_days=0.2, workload_mix=MIX,
                        dirty_rate=0.25, dirty_kinds=["malformed_json"])
    summary = run_test(cfg, "kafka", "127.0.0.1:9094", write_results=False)
    injected = summary["dirty_injected"]["malformed_json"]
    assert injected > 1000
    wait_for_rows(summary["test_run_id"], summary["events_emitted"])
    reasons = dict(run_query(f"""SELECT validation_error, count(*) FROM {T}.dead_letter_events
                                WHERE raw_value LIKE ? GROUP BY 1""", [f"%{summary['test_run_id']}%"]).rows)
    assert reasons == {"malformed_json": injected}
