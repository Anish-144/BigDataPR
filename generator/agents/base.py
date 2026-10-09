"""Data structures shared by the task factory, mock agents, evaluator and runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from security.policy_engine import Violation

PERFORMANCE_FAULTS = ("slow_tool", "tool_timeout", "loop", "malformed_response", "high_token_usage", "failed_retrieval")
SECURITY_FAULTS = (
    "suspicious_tool_access",
    "policy_violation",
    "prompt_injection",
    "sensitive_data_leak",
    "exfiltration_sequence",
    "privilege_escalation",
)
ALL_FAULTS = PERFORMANCE_FAULTS + SECURITY_FAULTS

# Which workloads a fault can be injected into.
FAULT_WORKLOADS: dict[str, frozenset[str]] = {
    "slow_tool": frozenset({"rag", "tool", "multi_step"}),
    "tool_timeout": frozenset({"rag", "tool", "multi_step"}),
    "loop": frozenset({"tool", "multi_step"}),
    "malformed_response": frozenset({"qa", "rag", "tool", "multi_step"}),
    "high_token_usage": frozenset({"qa", "rag", "tool", "multi_step"}),
    "failed_retrieval": frozenset({"rag", "multi_step"}),
    "suspicious_tool_access": frozenset({"qa", "rag", "tool", "multi_step"}),
    "policy_violation": frozenset({"qa", "rag", "tool", "multi_step"}),
    "prompt_injection": frozenset({"qa", "rag", "tool", "multi_step"}),
    "sensitive_data_leak": frozenset({"qa", "rag", "tool", "multi_step"}),
    "exfiltration_sequence": frozenset({"rag", "tool", "multi_step"}),
    "privilege_escalation": frozenset({"qa", "rag", "tool", "multi_step"}),
}

# Fault pairs that would mask each other (e.g. a failed retrieval prevents exposure to a poisoned document).
INCOMPATIBLE_FAULTS: frozenset[frozenset[str]] = frozenset({
    frozenset({"prompt_injection", "failed_retrieval"}),
    frozenset({"sensitive_data_leak", "malformed_response"}),
})

# Security categories each injected security fault is expected to surface
# (used by the detector evaluation, never by the detectors themselves).
EXPECTED_SECURITY_CATEGORIES: dict[str, frozenset[str]] = {
    "suspicious_tool_access": frozenset({"tool_not_allowlisted"}),
    "policy_violation": frozenset({"policy_violation"}),
    "prompt_injection": frozenset({"prompt_injection"}),
    "sensitive_data_leak": frozenset({"sensitive_data_output"}),
    "exfiltration_sequence": frozenset({"exfiltration_sequence"}),
    "privilege_escalation": frozenset({"privilege_escalation"}),
}


@dataclass
class Task:
    index: int
    task_id: str
    workload_type: str
    difficulty: str
    user_input: str
    reference_answer: str
    relevant_doc_ids: tuple[str, ...] = ()
    expected_tools: tuple[tuple[str, dict[str, Any]], ...] = ()
    faults: tuple[str, ...] = ()
    incident: str | None = None
    incident_effect: dict[str, float] = field(default_factory=dict)
    benign_near_miss: bool = False


@dataclass
class SpanRecord:
    span_id: str
    parent_span_id: str | None
    span_kind: str
    span_name: str
    start_ms: float  # offset from run start
    duration_ms: float
    status: str = "ok"
    error_category: str | None = None
    step_index: int = 0
    attempt: int = 1
    depth: int = 1
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    ttft_ms: float | None = None
    tool_name: str | None = None
    tool_args_valid: bool | None = None
    tool_allowed: bool | None = None
    policy_decision: str | None = None
    data_classification: str | None = None
    retrieved_doc_ids: list[str] | None = None
    retrieval_scores: list[float] | None = None
    top_k: int | None = None
    delegated_agent_id: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


@dataclass
class ToolCallRecord:
    tool_name: str
    args: dict[str, Any]
    allowed: bool
    status: str  # ok | error | timeout | denied
    args_valid: bool
    latency_ms: float
    span_id: str
    attempts: int = 1
    result: dict[str, Any] | None = None


@dataclass
class ExecutionResult:
    start: datetime
    spans: list[SpanRecord]
    status: str  # completed | failed | timeout
    error_category: str | None
    output_text: str
    answer: str | None
    citations: list[str]
    retrieved: list[tuple[str, float]]
    tool_calls: list[ToolCallRecord]
    violations: list[Violation]
    input_tokens: int
    output_tokens: int
    llm_calls: int
    retries: int
    ttft_ms: float | None
    top_k: int | None = None
    exposed_docs: list[str] = field(default_factory=list)

    @property
    def latency_ms(self) -> float:
        return self.spans[0].duration_ms if self.spans else 0.0
