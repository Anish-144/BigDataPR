"""Policy-as-code engine: evaluates tool calls, data access and role changes
against ``config/policies.yaml``. Pure functions over plain data; no tool is
ever executed because of text found in a prompt or document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.config import load_policy
from generator.agents.corpus import CLASSIFICATION_RANK


@dataclass(frozen=True)
class Violation:
    rule_id: str
    rule_name: str
    category: str
    severity: str
    action: str  # blocked | flagged | allowed
    detector: str
    evidence: str
    span_id: str | None = None
    tool_name: str | None = None


@dataclass
class ToolDecision:
    allowed: bool
    decision: str  # allow | deny
    violations: list[Violation] = field(default_factory=list)


class PolicyEngine:
    def __init__(self, policy: dict[str, Any] | None = None):
        self.policy = policy or load_policy()
        self.version: str = self.policy["policy_version"]
        self.rules = {r["rule_id"]: r for r in self.policy["rules"]}
        self.prohibited = set(self.policy["prohibited_tools"])
        self.egress = set(self.policy["egress_tools"])
        self.restricted_resources = set(self.policy["restricted_resources"])
        priv = self.policy["privilege"]
        self.expected_role = priv["expected_role"]
        self.elevated_roles = set(priv["elevated_roles"])

    def agent_policy(self, agent_id: str) -> dict[str, Any]:
        # Unknown agents get a deny-all policy rather than an implicit allow.
        return self.policy["agents"].get(
            agent_id, {"allowed_tools": [], "max_tool_calls": 0, "max_data_classification": "public"}
        )

    def violation(
        self, rule_id: str, action: str, evidence: str, detector: str = "runtime_policy_engine", **kw: Any
    ) -> Violation:
        r = self.rules[rule_id]
        return Violation(
            rule_id=rule_id,
            rule_name=r["rule_name"],
            category=r["category"],
            severity=r["severity"],
            action=action,
            detector=detector,
            evidence=evidence,
            **kw,
        )

    def check_tool_call(self, agent_id: str, tool_name: str, calls_so_far: int, span_id: str | None = None) -> ToolDecision:
        ap = self.agent_policy(agent_id)
        violations: list[Violation] = []
        if tool_name in self.prohibited:
            violations.append(
                self.violation("SEC-002", "blocked", f"tool '{tool_name}' is globally prohibited", span_id=span_id, tool_name=tool_name)
            )
        elif tool_name not in ap["allowed_tools"]:
            violations.append(
                self.violation(
                    "SEC-001", "blocked",
                    f"tool '{tool_name}' not in allowlist {sorted(ap['allowed_tools'])} for {agent_id}",
                    span_id=span_id, tool_name=tool_name,
                )
            )
        if not violations and calls_so_far >= ap["max_tool_calls"]:
            violations.append(
                self.violation(
                    "SEC-008", "blocked",
                    f"tool call #{calls_so_far + 1} exceeds max_tool_calls={ap['max_tool_calls']}",
                    span_id=span_id, tool_name=tool_name,
                )
            )
        return ToolDecision(allowed=not violations, decision="deny" if violations else "allow", violations=violations)

    def check_data_access(
        self, agent_id: str, classification: str, resource: str | None, doc_id: str, span_id: str | None = None
    ) -> list[Violation]:
        ap = self.agent_policy(agent_id)
        limit = CLASSIFICATION_RANK[ap["max_data_classification"]]
        if CLASSIFICATION_RANK.get(classification, 3) > limit or (resource and resource in self.restricted_resources):
            return [
                self.violation(
                    "SEC-003", "flagged",
                    f"read {doc_id} ({classification}{', ' + resource if resource else ''}) above "
                    f"max_data_classification={ap['max_data_classification']}",
                    span_id=span_id,
                )
            ]
        return []

    def check_role(self, observed_role: str, span_id: str | None = None) -> list[Violation]:
        if observed_role != self.expected_role and observed_role in self.elevated_roles:
            return [
                self.violation(
                    "SEC-006", "flagged",
                    f"runtime role changed {self.expected_role} -> {observed_role}", span_id=span_id,
                )
            ]
        return []

    def is_egress(self, tool_name: str) -> bool:
        return tool_name in self.egress
