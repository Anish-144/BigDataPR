"""Investigation assistant: intent routing, grounding/decline behaviour and the optional LLM adapter."""

from __future__ import annotations

import types

import pytest

from common import llm
from investigation import answer_service as svc
from investigation.retrieval import retriever


@pytest.mark.parametrize("question,intent", [
    ("Why did run R-104 fail?", "run_diagnosis"),
    ("Compare agent version v1 and v2 for latency, cost, and task success.", "version_compare"),
    ("Show the main causes of timeouts during the last test.", "timeout_causes"),
    ("Why was this tool call flagged?", "flagged_explain"),
    ("What changed in the last regression run?", "regression_changes"),
    ("Suggest improvements for the highest-cost agent.", "cost_improvements"),
    ("Explain alert A-0123456789abcdef", "alert_explain"),
    ("Which versions have the worst p95?", "latency_overview"),
])
def test_spec_questions_route_to_intents(question, intent):
    assert svc.classify(question, svc.Context()) == intent


def test_context_run_with_policy_words_routes_to_flag_explanation():
    ctx = svc.Context(run_id="R-abcdef-000001")
    assert svc.classify("why was this blocked by policy?", ctx) == "flagged_explain"
    assert svc.classify("what happened here?", ctx) == "run_diagnosis"


def test_unrelated_question_declines_without_guessing():
    ans = svc.knowledge("What is the weather in Paris tomorrow?", svc.Context())
    assert not ans.grounded and ans.evidence == [] and "will not guess" in ans.answer


def test_retrieval_finds_relevant_runbook():
    hits = retriever().search("tool timeout retries circuit breaker")
    assert hits and hits[0][0].passage_id.startswith("kb:tool_timeouts")


def test_run_diagnosis_cites_trace_evidence(monkeypatch):
    run = {"run_id": "R-aaaaaa-000104", "trace_id": "a" * 32, "test_run_id": "TR-20261009-aaaaaa", "agent_id": "ops-tool-agent",
           "agent_version": "1.0.0", "event_time": "2026-10-09T10:00:00"}
    metrics = {**run, "status": "timeout", "error_category": "tool_timeout", "task_success": False, "model_name": "mock-small",
               "prompt_version": "ops-p1", "latency_ms": 24500.0, "total_tokens": 900, "tool_calls": 3, "retries": 2,
               "injected_faults": ["tool_timeout"]}
    span = {"span_id": "b" * 16, "span_kind": "tool_call", "span_name": "tool:get_order_status", "duration_ms": 8000.0,
            "status": "timeout", "error_category": "tool_timeout", "attempt": 3, "tool_name": "get_order_status", "policy_decision": "allow"}

    def fake_q(sql, params=None, max_rows=200):
        if "FROM lakehouse.analytics.agent_spans" in sql:
            return [span]
        if "approx_percentile" in sql:
            return [{"p50": 1200.0, "p95": 2100.0}]
        if "SELECT *" in sql:
            return [metrics]
        if "agent_run_metrics" in sql:
            return [run]
        return []

    monkeypatch.setattr(svc, "q", fake_q)
    ans = svc.run_diagnosis("Why did run R-aaaaaa-000104 fail?", svc.Context())
    assert ans.grounded and "failed" in ans.answer and "get_order_status" in ans.answer
    refs = {e.ref for e in ans.evidence}
    assert "R-aaaaaa-000104" in refs and f"{'a' * 32}/{'b' * 16}" in refs
    assert any(e.kind == "document" for e in ans.evidence)  # runbook guidance retrieved for tool timeouts
    assert "synthetic label" in ans.answer  # ground truth is labelled as such


def test_unknown_run_declines(monkeypatch):
    monkeypatch.setattr(svc, "q", lambda *a, **k: [])
    ans = svc.run_diagnosis("Why did run R-999999 fail?", svc.Context())
    assert not ans.grounded and "No run matching" in ans.answer


def test_llm_disabled_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("s", "u")


class _FakeMessages:
    def __init__(self, response):
        self.response, self.calls = response, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _fake_client(response):
    msgs = _FakeMessages(response)
    client = types.SimpleNamespace(messages=msgs, beta=types.SimpleNamespace(messages=msgs))
    return client, msgs


def test_llm_request_shape_and_refusal(monkeypatch):
    import anthropic

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    ok = types.SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                               content=[types.SimpleNamespace(type="text", text="grounded answer")],
                               usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))
    client, msgs = _fake_client(ok)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    res = llm.complete("system", "user", effort="low")
    call = msgs.calls[-1]
    assert res.text == "grounded answer"
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"] and call["output_config"] == {"effort": "low"}
    assert "thinking" not in call  # thinking cannot be disabled on this model; effort is the control

    refusal = types.SimpleNamespace(stop_reason="refusal", model="claude-opus-5-5", content=[],
                                    stop_details=types.SimpleNamespace(category="cyber"), usage=None)
    client2, _ = _fake_client(refusal)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client2)
    with pytest.raises(llm.LLMUnavailable, match="declined"):
        llm.complete("system", "user")


def test_investigate_falls_back_to_deterministic_when_llm_fails(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(svc, "classify", lambda q, c: "knowledge")
    monkeypatch.setitem(svc.HANDLERS, "knowledge", lambda q, c: svc.Answer(q, "knowledge", "deterministic text",
                                                                            [svc.Evidence("document", "kb:x", "X")]))

    def boom(*a, **k):
        raise llm.LLMUnavailable("connection error")

    monkeypatch.setattr(llm, "complete", boom)
    ans = svc.investigate("anything")
    assert ans.mode == "deterministic" and ans.answer == "deterministic text" and "LLM unavailable" in ans.llm_note

    monkeypatch.setattr(llm, "complete", lambda *a, **k: llm.LLMResult("rephrased", "claude-opus-5-5", "end_turn", 1, 1))
    ans = svc.investigate("anything")
    assert ans.mode == "llm" and ans.answer == "rephrased" and ans.evidence[0].ref == "kb:x"  # evidence unchanged


def test_llm_judge_is_labelled_and_optional(monkeypatch):
    from evaluation import llm_judge

    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert llm_judge.judge_groundedness("q", [("KB-001", "text")], "answer") is None  # no LLM -> no record

    monkeypatch.setattr(llm, "complete", lambda *a, **k: llm.LLMResult(
        'Here: {"score": 5, "grounded": true, "explanation": "fully supported"}', "claude-opus-5-5", "end_turn", 1, 1))
    rec = llm_judge.judge_groundedness("q", [("KB-001", "text")], "answer")
    assert rec.evaluator_type == "model_judge" and rec.score == 5.0 and rec.passed is True and rec.rubric

    monkeypatch.setattr(llm, "complete", lambda *a, **k: llm.LLMResult("not json", "m", "end_turn", 1, 1))
    assert llm_judge.judge_groundedness("q", [], "a") is None  # unusable judge output is dropped, not guessed
    assert llm_judge.consistency([(True, 0.8), (False, 0.2), (True, 0.1)])["agreement"] == pytest.approx(0.6667, abs=1e-3)


def test_runner_without_llm_emits_no_judge_records():
    from generator.runner import TestRunConfig, execute_task, make_context

    cfg = TestRunConfig(name="judge", seed=3, tasks=40, llm_judge_rate=1.0,
                        workload_mix=[{"agent_id": "rag-helpdesk", "version": "2.0.0", "weight": 1}])
    ctx = make_context(cfg, test_run_id="TR-20261009-0abc99")
    events = [e for i in range(40) for e in execute_task(ctx, i, "w0")]
    assert not [e for e in events if e.event_type == "evaluation.result" and e.payload.evaluator_type == "model_judge"]
