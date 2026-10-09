"""AgentShield shared telemetry contract.

Every event published to Kafka is an ``Event`` envelope with a typed ``payload``.
The envelope carries the identifiers that every downstream module uses
consistently (``test_run_id``, ``run_id``, ``trace_id``, ``agent_id``,
``agent_version``, ``scenario_id``, ``event_time``). ``event_date`` is derived
(UTC date of ``event_time``) by the stream processor.

Identifier semantics
--------------------
* ``test_run_id``  - one benchmark / test run (a batch of tasks), e.g. ``TR-20261009-7f3a9c``.
* ``run_id``       - one agent run = one task execution, e.g. ``R-7f3a9c-000104``.
* ``trace_id``     - OpenTelemetry-style 32-hex trace id; 1:1 with ``run_id``.
* ``span_id``      - OpenTelemetry-style 16-hex span id inside a trace.

The span model follows the spirit of the OpenTelemetry GenAI semantic
conventions (operation kind, model name, token usage, tool name) with
project-specific extensions documented in docs/DATA_DICTIONARY.md.

Schema versions
---------------
* ``1.0`` - initial contract.
* ``1.1`` - adds the optional ``RunMetricsPayload.routing_strategy`` field
  (schema-evolution demonstration; old events simply carry ``null``).

Raw prompts/completions are never part of the contract. Content capture is
opt-in and limited to redacted, truncated previews in ``SpanPayload.attributes``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")


class Topic(str, Enum):
    TRACES = "agent-traces"
    METRICS = "agent-metrics"
    EVALUATIONS = "agent-evaluations"
    SECURITY = "agent-security-events"
    ALERTS = "agent-alerts"
    DLQ = "agent-events-dlq"


class EventType(str, Enum):
    TEST_RUN_STARTED = "test_run.started"
    TEST_RUN_COMPLETED = "test_run.completed"
    SPAN_COMPLETED = "span.completed"
    RUN_METRICS = "run.metrics"
    WORKER_RESOURCE = "worker.resource"
    EVALUATION_RESULT = "evaluation.result"
    SECURITY_FINDING = "security.finding"
    ANOMALY_ALERT = "anomaly.alert"


EVENT_TOPIC: dict[EventType, Topic] = {
    EventType.TEST_RUN_STARTED: Topic.TRACES,
    EventType.TEST_RUN_COMPLETED: Topic.TRACES,
    EventType.SPAN_COMPLETED: Topic.TRACES,
    EventType.RUN_METRICS: Topic.METRICS,
    EventType.WORKER_RESOURCE: Topic.METRICS,
    EventType.EVALUATION_RESULT: Topic.EVALUATIONS,
    EventType.SECURITY_FINDING: Topic.SECURITY,
    EventType.ANOMALY_ALERT: Topic.ALERTS,
}

DATA_TOPICS: tuple[Topic, ...] = (
    Topic.TRACES,
    Topic.METRICS,
    Topic.EVALUATIONS,
    Topic.SECURITY,
    Topic.ALERTS,
)


class SpanKind(str, Enum):
    AGENT = "agent"
    PLANNING = "planning"
    LLM_CALL = "llm_call"
    RETRIEVAL = "retrieval"
    TOOL_CALL = "tool_call"
    POLICY_CHECK = "policy_check"
    EVALUATION = "evaluation"
    DELEGATION = "delegation"


class Status(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


class RunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EvaluatorType(str, Enum):
    DETERMINISTIC = "deterministic"
    MODEL_JUDGE = "model_judge"
    HUMAN = "human"


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware (UTC)")
    return value.astimezone(timezone.utc)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# --------------------------------------------------------------------------- payloads


class TestRunPayload(_Strict):
    test_run_name: str
    status: Literal["running", "completed", "stopped", "failed"]
    seed: int
    requested_tasks: int = Field(ge=0)
    workers: int = Field(ge=1)
    time_mode: Literal["realtime", "simulated"]
    scenario_file: str | None = None
    workload_mix: str  # JSON string: [{agent_id, agent_version, weight}]
    fault_profile: str  # JSON string: {fault_name: rate}
    started_at: datetime
    ended_at: datetime | None = None
    sim_window_start: datetime | None = None  # simulated event-time window (time_mode=simulated)
    sim_window_end: datetime | None = None
    total_runs: int | None = None
    total_events: int | None = None
    triggered_by: str = "cli"
    notes: str | None = None

    @field_validator("started_at", "ended_at", "sim_window_start", "sim_window_end")
    @classmethod
    def check_utc(cls, v):
        return None if v is None else _require_utc(v)


class SpanPayload(_Strict):
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    parent_span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    span_kind: SpanKind
    span_name: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status: Status
    error_category: str | None = None
    step_index: int = Field(ge=0)
    attempt: int = Field(default=1, ge=1)
    model_name: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    ttft_ms: float | None = None
    tool_name: str | None = None
    tool_args_valid: bool | None = None
    tool_allowed: bool | None = None
    policy_decision: Literal["allow", "deny", "flag"] | None = None
    data_classification: str | None = None
    retrieved_doc_ids: list[str] | None = None
    retrieval_scores: list[float] | None = None
    top_k: int | None = None
    delegated_agent_id: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("start_time", "end_time")
    @classmethod
    def check_utc(cls, v):
        return _require_utc(v)


class RunMetricsPayload(_Strict):
    agent_name: str
    agent_release_seq: int
    model_name: str
    prompt_version: str
    workload_type: Literal["qa", "rag", "tool", "multi_step"]
    difficulty: Literal["easy", "medium", "hard"]
    task_id: str
    status: RunStatus
    task_success: bool
    start_time: datetime
    end_time: datetime
    latency_ms: float
    ttft_ms: float | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_errors: int = Field(ge=0)
    tool_timeouts: int = Field(ge=0)
    retries: int = Field(ge=0)
    span_count: int = Field(ge=1)
    max_depth: int = Field(ge=1)
    distinct_tools: int = Field(ge=0)
    max_consecutive_same_tool: int = Field(ge=0)
    avg_tool_latency_ms: float | None = None
    retrieval_count: int = Field(ge=0)
    policy_denials: int = Field(ge=0)
    error_category: str | None = None
    estimated_cost_usd: float | None = None
    cost_source: str  # "local_pricing_config:<version>" or "unavailable"
    injected_faults: list[str] = Field(default_factory=list)  # synthetic ground-truth labels
    worker_id: str
    routing_strategy: str | None = None  # added in schema 1.1

    @field_validator("start_time", "end_time")
    @classmethod
    def check_utc(cls, v):
        return _require_utc(v)


class WorkerResourcePayload(_Strict):
    worker_id: str
    cpu_percent: float | None = None
    memory_mb: float | None = None
    tasks_completed: int = Field(ge=0)
    events_emitted: int = Field(ge=0)
    events_per_sec: float | None = None
    interval_s: float


class EvaluationPayload(_Strict):
    evaluation_id: str
    evaluator_name: str
    evaluator_version: str
    evaluator_type: EvaluatorType
    metric_name: str
    score: float | None = None
    passed: bool | None = None
    threshold: float | None = None
    rubric: str | None = None
    evidence: str | None = None
    judge_model: str | None = None  # only for evaluator_type=model_judge


class SecurityFindingPayload(_Strict):
    finding_id: str
    rule_id: str
    rule_name: str
    category: str
    severity: Severity
    span_id: str | None = None
    tool_name: str | None = None
    action: Literal["blocked", "flagged", "allowed"]
    policy_version: str
    detector: str
    evidence: str


class AnomalyAlertPayload(_Strict):
    alert_id: str
    detector: str
    detector_version: str
    anomaly_type: str
    severity: Severity
    score: float
    window_start: datetime
    window_end: datetime
    agent_name: str | None = None
    related_run_ids: list[str] = Field(default_factory=list)
    related_trace_ids: list[str] = Field(default_factory=list)
    supporting_metrics: dict[str, float] = Field(default_factory=dict)
    explanation: str

    @field_validator("window_start", "window_end")
    @classmethod
    def check_utc(cls, v):
        return _require_utc(v)


# --------------------------------------------------------------------------- envelope


class _EnvelopeBase(_Strict):
    event_id: str = Field(min_length=8)
    schema_version: str = SCHEMA_VERSION
    event_time: datetime
    producer: str
    test_run_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    agent_id: str | None = None
    agent_version: str | None = None
    scenario_id: str | None = None

    @field_validator("event_time")
    @classmethod
    def check_utc(cls, v):
        return _require_utc(v)

    @field_validator("schema_version")
    @classmethod
    def check_schema_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported schema_version {v!r}")
        return v

    @property
    def topic(self) -> Topic:
        return EVENT_TOPIC[EventType(self.event_type)]  # type: ignore[attr-defined]

    def kafka_key(self) -> str:
        return self.trace_id or self.test_run_id or self.event_id

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=False)


class TestRunStartedEvent(_EnvelopeBase):
    event_type: Literal["test_run.started"] = "test_run.started"
    payload: TestRunPayload


class TestRunCompletedEvent(_EnvelopeBase):
    event_type: Literal["test_run.completed"] = "test_run.completed"
    payload: TestRunPayload


class SpanEvent(_EnvelopeBase):
    event_type: Literal["span.completed"] = "span.completed"
    payload: SpanPayload


class RunMetricsEvent(_EnvelopeBase):
    event_type: Literal["run.metrics"] = "run.metrics"
    payload: RunMetricsPayload


class WorkerResourceEvent(_EnvelopeBase):
    event_type: Literal["worker.resource"] = "worker.resource"
    payload: WorkerResourcePayload


class EvaluationEvent(_EnvelopeBase):
    event_type: Literal["evaluation.result"] = "evaluation.result"
    payload: EvaluationPayload


class SecurityFindingEvent(_EnvelopeBase):
    event_type: Literal["security.finding"] = "security.finding"
    payload: SecurityFindingPayload


class AnomalyAlertEvent(_EnvelopeBase):
    event_type: Literal["anomaly.alert"] = "anomaly.alert"
    payload: AnomalyAlertPayload


Event = Annotated[
    Union[
        TestRunStartedEvent,
        TestRunCompletedEvent,
        SpanEvent,
        RunMetricsEvent,
        WorkerResourceEvent,
        EvaluationEvent,
        SecurityFindingEvent,
        AnomalyAlertEvent,
    ],
    Field(discriminator="event_type"),
]

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

EVENT_MODELS: dict[EventType, type[_EnvelopeBase]] = {
    EventType.TEST_RUN_STARTED: TestRunStartedEvent,
    EventType.TEST_RUN_COMPLETED: TestRunCompletedEvent,
    EventType.SPAN_COMPLETED: SpanEvent,
    EventType.RUN_METRICS: RunMetricsEvent,
    EventType.WORKER_RESOURCE: WorkerResourceEvent,
    EventType.EVALUATION_RESULT: EvaluationEvent,
    EventType.SECURITY_FINDING: SecurityFindingEvent,
    EventType.ANOMALY_ALERT: AnomalyAlertEvent,
}

# Envelope fields that must be present for each event type (beyond the always-required ones).
REQUIRED_CONTEXT: dict[EventType, tuple[str, ...]] = {
    EventType.TEST_RUN_STARTED: ("test_run_id",),
    EventType.TEST_RUN_COMPLETED: ("test_run_id",),
    EventType.SPAN_COMPLETED: ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    EventType.RUN_METRICS: ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    EventType.WORKER_RESOURCE: ("test_run_id",),
    EventType.EVALUATION_RESULT: ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    EventType.SECURITY_FINDING: ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version"),
    EventType.ANOMALY_ALERT: (),
}


def parse_event(raw: str | bytes) -> Event:
    """Validate a raw JSON event against the contract (raises ``pydantic.ValidationError``)."""
    event = EVENT_ADAPTER.validate_json(raw)
    missing = [f for f in REQUIRED_CONTEXT[EventType(event.event_type)] if getattr(event, f) is None]
    if missing:
        raise ValueError(f"{event.event_type} event missing required context fields: {missing}")
    return event


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
