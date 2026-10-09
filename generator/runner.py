"""Turns a test-run configuration into a deterministic stream of telemetry events.

Planning is a pure function of (seed, task index): agent/version choice,
difficulty, injected faults and the simulated start time all come from a
per-task RNG, so the same seed reproduces the same runs regardless of the
number of workers.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from common import ids, llm
from common.config import AgentVersion, estimate_cost, load_agents
from evaluation.task_evaluator import evaluate
from generator import event_schema as es
from generator.agents.base import FAULT_WORKLOADS, INCOMPATIBLE_FAULTS, ExecutionResult, Task
from generator.agents.corpus import DOC_BY_ID
from generator.agents.mock_agents import AgentSimulator
from generator.agents.tasks import build_task

PRODUCER = "agentshield-generator/1.0"


class MixEntry(BaseModel):
    agent_id: str
    version: str
    weight: float = Field(gt=0)


class Incident(BaseModel):
    name: str
    agent_id: str
    version: str | None = None
    start_pct: float = Field(ge=0, le=1)
    duration_pct: float = Field(gt=0, le=1)
    effect: dict[str, float]


class TestRunConfig(BaseModel):
    __test__ = False  # not a pytest test class
    name: str = "adhoc"
    description: str | None = None
    seed: int = 42
    tasks: int = Field(default=1000, ge=1, le=5_000_000)
    workers: int = Field(default=2, ge=1, le=32)
    time_mode: str = Field(default="simulated", pattern="^(simulated|realtime)$")
    sim_days: float = Field(default=2.0, gt=0, le=60)
    sim_end: datetime | None = None
    rate_per_sec: float = Field(default=0.0, ge=0)  # realtime throttle in tasks/s (0 = unthrottled)
    workload_mix: list[MixEntry]
    fault_profile: dict[str, float] = Field(default_factory=dict)
    max_faults_per_run: int = Field(default=2, ge=0, le=4)
    incidents: list[Incident] = Field(default_factory=list)
    dirty_rate: float = Field(default=0.0, ge=0, le=0.5)
    dirty_kinds: list[str] | None = None  # subset of ingestion.validation.DIRTY_KINDS (default: all)
    scenario_file: str | None = None
    triggered_by: str = "cli"
    notes: str | None = None
    capture_content: bool = False
    llm_judge_rate: float = Field(default=0.0, ge=0, le=1)  # optional model judge on sampled RAG runs

    @classmethod
    def from_yaml(cls, path: str | Path, **overrides: Any) -> "TestRunConfig":
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        data.update({k: v for k, v in overrides.items() if v is not None})
        data.setdefault("scenario_file", str(Path(path).as_posix()))
        return cls(**data)


@dataclass
class PlannedTask:
    index: int
    av: AgentVersion
    task: Task
    scheduled_at: datetime
    load_factor: float


@dataclass
class RunContext:
    cfg: TestRunConfig
    test_run_id: str
    window_start: datetime
    window_end: datetime
    agents: dict[str, AgentVersion]
    simulator: AgentSimulator
    _cum: list[tuple[float, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        unknown = [f"{m.agent_id}@{m.version}" for m in self.cfg.workload_mix if f"{m.agent_id}@{m.version}" not in self.agents]
        if unknown:
            raise ValueError(f"workload_mix references unknown agent versions: {unknown}")
        total = sum(m.weight for m in self.cfg.workload_mix)
        acc = 0.0
        for m in self.cfg.workload_mix:
            acc += m.weight / total
            self._cum.append((acc, f"{m.agent_id}@{m.version}"))


def make_context(cfg: TestRunConfig, test_run_id: str | None = None, now: datetime | None = None) -> RunContext:
    now = now or datetime.now(timezone.utc)
    end = (cfg.sim_end or now).astimezone(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=cfg.sim_days)
    if test_run_id is None:
        test_run_id = ids.test_run_id(now.strftime("%Y%m%d"), ids.task_rng(cfg.seed, -1, salt=now.isoformat()))
    return RunContext(cfg, test_run_id, start, end, load_agents(), AgentSimulator(capture_content=cfg.capture_content))


def _load_factor(ts: datetime) -> float:
    """Mild diurnal load pattern for simulated time (peak around 15:00 UTC)."""
    return 1.0 + 0.12 * math.exp(-((ts.hour + ts.minute / 60 - 15) ** 2) / 8)


def plan_task(ctx: RunContext, i: int):
    cfg = ctx.cfg
    rng = ids.task_rng(cfg.seed, i)
    u = rng.random()
    key = next(k for c, k in ctx._cum if u <= c + 1e-12)
    av = ctx.agents[key]
    frac = (i + rng.random()) / cfg.tasks
    if cfg.time_mode == "simulated":
        scheduled = ctx.window_start + (ctx.window_end - ctx.window_start) * frac
    else:
        scheduled = datetime.now(timezone.utc)
    faults: list[str] = []
    for fault in sorted(cfg.fault_profile):
        rate = cfg.fault_profile[fault]
        if rng.random() < rate and av.workload_type in FAULT_WORKLOADS.get(fault, ()) and len(faults) < cfg.max_faults_per_run:
            if not any(frozenset((fault, f)) in INCOMPATIBLE_FAULTS for f in faults):
                faults.append(fault)
    task = build_task(i, av.workload_type, rng, tuple(faults))
    for inc in cfg.incidents:
        if inc.agent_id == av.agent_id and (inc.version in (None, av.version)) and inc.start_pct <= frac < inc.start_pct + inc.duration_pct:
            task.incident = inc.name
            task.incident_effect = dict(inc.effect)
            break
    load = _load_factor(scheduled) if cfg.time_mode == "simulated" else 1.0
    return PlannedTask(i, av, task, scheduled, load), rng


def _labels(task: Task, result: ExecutionResult) -> list[str]:
    labels = list(task.faults)
    if task.incident:
        labels.append(f"incident:{task.incident}")
    # Ground truth: a poisoned document's *content* reached the agent (search_kb id lists do not count).
    if "prompt_injection" not in labels and any(DOC_BY_ID[d].contains_injection for d in result.exposed_docs):
        labels.append("poisoned_document_retrieved")
    return labels


def _max_consecutive_same_tool(result: ExecutionResult) -> int:
    best = run = 0
    prev = None
    for s in result.spans:
        if s.span_kind != "tool_call" or s.attempt > 1:
            continue
        run = run + 1 if s.tool_name == prev else 1
        prev = s.tool_name
        best = max(best, run)
    return best


def execute_task(ctx: RunContext, i: int, worker_id: str) -> list[es._EnvelopeBase]:
    """Plan, simulate, evaluate and convert one task into contract events."""
    planned, rng = plan_task(ctx, i)
    av, task = planned.av, planned.task
    result = ctx.simulator.run(task, av, rng, planned.scheduled_at, planned.load_factor)
    if ctx.cfg.time_mode == "realtime":
        result.start = datetime.now(timezone.utc) - timedelta(milliseconds=result.latency_ms)
    else:
        result.start = planned.scheduled_at
    records, success = evaluate(task, result)
    if ctx.cfg.llm_judge_rate > 0 and task.relevant_doc_ids and ids.task_rng(ctx.cfg.seed, i, salt="judge").random() < ctx.cfg.llm_judge_rate:
        from evaluation.llm_judge import judge_groundedness  # optional; returns None when no LLM is configured

        docs = [(d, DOC_BY_ID[d].text) for d, _ in result.retrieved if d in DOC_BY_ID]
        judged = judge_groundedness(task.user_input, docs, result.output_text)
        if judged is not None:
            records.append(judged)

    run_id = ids.run_id(ctx.test_run_id, i)
    trace = ids.scoped(ctx.test_run_id, ids.trace_id(rng))
    sid = {sp.span_id: ids.scoped(ctx.test_run_id, sp.span_id) for sp in result.spans}
    envelope = dict(
        producer=PRODUCER, test_run_id=ctx.test_run_id, run_id=run_id, trace_id=trace,
        agent_id=av.agent_id, agent_version=av.version, scenario_id=ctx.cfg.name,
    )
    start = result.start
    at = lambda ms: start + timedelta(milliseconds=ms)  # noqa: E731
    events: list[es._EnvelopeBase] = []

    if task.benign_near_miss:
        result.spans[0].attributes["test_case"] = "benign_near_miss"
    for s in sorted(result.spans, key=lambda s: s.end_ms):
        attrs = dict(s.attributes)
        attrs["depth"] = str(s.depth)
        events.append(
            es.SpanEvent(
                event_id=ids.scoped_event_id(ctx.test_run_id, ids.event_id(rng)), event_time=at(s.end_ms), **envelope,
                payload=es.SpanPayload(
                    span_id=sid[s.span_id], parent_span_id=sid.get(s.parent_span_id), span_kind=s.span_kind, span_name=s.span_name,
                    start_time=at(s.start_ms), end_time=at(s.end_ms), duration_ms=s.duration_ms, status=s.status,
                    error_category=s.error_category, step_index=s.step_index, attempt=s.attempt, model_name=s.model_name,
                    input_tokens=s.input_tokens, output_tokens=s.output_tokens, ttft_ms=s.ttft_ms, tool_name=s.tool_name,
                    tool_args_valid=s.tool_args_valid, tool_allowed=s.tool_allowed, policy_decision=s.policy_decision,
                    data_classification=s.data_classification, retrieved_doc_ids=s.retrieved_doc_ids,
                    retrieval_scores=s.retrieval_scores, top_k=s.top_k, delegated_agent_id=s.delegated_agent_id,
                    attributes=attrs,
                ),
            )
        )

    span_end = {sid[s.span_id]: s.end_ms for s in result.spans}
    for v in result.violations:
        v_sid = sid.get(v.span_id) if v.span_id else None
        events.append(
            es.SecurityFindingEvent(
                event_id=ids.scoped_event_id(ctx.test_run_id, ids.event_id(rng)), event_time=at(span_end.get(v_sid, result.latency_ms)), **envelope,
                payload=es.SecurityFindingPayload(
                    finding_id=ids.stable_id(run_id, v.rule_id, v_sid, v.evidence, prefix="F-", n=16),
                    rule_id=v.rule_id, rule_name=v.rule_name, category=v.category, severity=v.severity,
                    span_id=v_sid, tool_name=v.tool_name, action=v.action,
                    policy_version=ctx.simulator.engine.version, detector=v.detector, evidence=v.evidence,
                ),
            )
        )

    tool_spans = [s for s in result.spans if s.span_kind == "tool_call"]
    executed = [s for s in tool_spans if s.tool_allowed]
    cost, cost_source = estimate_cost(av.model_name, result.input_tokens, result.output_tokens)
    end_time = at(result.latency_ms)
    events.append(
        es.RunMetricsEvent(
            event_id=ids.scoped_event_id(ctx.test_run_id, ids.event_id(rng)), event_time=end_time, **envelope,
            payload=es.RunMetricsPayload(
                agent_name=av.agent_name, agent_release_seq=av.release_seq, model_name=av.model_name,
                prompt_version=av.prompt_version, workload_type=av.workload_type, difficulty=task.difficulty,
                task_id=task.task_id, status=result.status, task_success=success, start_time=start, end_time=end_time,
                latency_ms=round(result.latency_ms, 3), ttft_ms=result.ttft_ms, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, llm_calls=result.llm_calls, tool_calls=len(tool_spans),
                tool_errors=sum(1 for s in tool_spans if s.status == "error"),
                tool_timeouts=sum(1 for s in tool_spans if s.status == "timeout"), retries=result.retries,
                span_count=len(result.spans), max_depth=max(s.depth for s in result.spans),
                distinct_tools=len({s.tool_name for s in tool_spans}),
                max_consecutive_same_tool=_max_consecutive_same_tool(result),
                avg_tool_latency_ms=round(sum(s.duration_ms for s in executed) / len(executed), 3) if executed else None,
                retrieval_count=sum(1 for s in result.spans if s.span_kind == "retrieval"),
                policy_denials=sum(1 for s in tool_spans if s.policy_decision == "deny"),
                error_category=result.error_category, estimated_cost_usd=cost, cost_source=cost_source,
                injected_faults=_labels(task, result), worker_id=worker_id,
                routing_strategy="static",
            ),
        )
    )

    eval_time = end_time + timedelta(milliseconds=rng.uniform(5, 40))
    for rec in records:
        events.append(
            es.EvaluationEvent(
                event_id=ids.scoped_event_id(ctx.test_run_id, ids.event_id(rng)), event_time=eval_time, **envelope,
                payload=es.EvaluationPayload(
                    evaluation_id=ids.stable_id(run_id, rec.evaluator_name, rec.metric_name, prefix="EV-", n=16),
                    evaluator_name=rec.evaluator_name, evaluator_version=rec.evaluator_version,
                    evaluator_type=rec.evaluator_type, metric_name=rec.metric_name, score=rec.score, passed=rec.passed,
                    threshold=rec.threshold, rubric=rec.rubric, evidence=rec.evidence,
                    judge_model=llm.model_name() if rec.evaluator_type == "model_judge" else None,
                ),
            )
        )
    return events


def test_run_event(ctx: RunContext, kind: str, status: str, started_at: datetime, **extra: Any) -> es._EnvelopeBase:
    cfg = ctx.cfg
    payload = es.TestRunPayload(
        test_run_name=cfg.name, status=status, seed=cfg.seed, requested_tasks=cfg.tasks, workers=cfg.workers,
        time_mode=cfg.time_mode, scenario_file=cfg.scenario_file,
        workload_mix=json.dumps([m.model_dump() for m in cfg.workload_mix]),
        fault_profile=json.dumps(cfg.fault_profile, sort_keys=True), started_at=started_at,
        sim_window_start=ctx.window_start if cfg.time_mode == "simulated" else None,
        sim_window_end=ctx.window_end if cfg.time_mode == "simulated" else None,
        triggered_by=cfg.triggered_by, notes=cfg.notes, **extra,
    )
    model = es.TestRunStartedEvent if kind == "started" else es.TestRunCompletedEvent
    rng = ids.task_rng(cfg.seed, -2, salt=f"{ctx.test_run_id}:{kind}")
    return model(event_id=ids.event_id(rng), event_time=datetime.now(timezone.utc), producer=PRODUCER,
                 test_run_id=ctx.test_run_id, scenario_id=cfg.name, payload=payload)
