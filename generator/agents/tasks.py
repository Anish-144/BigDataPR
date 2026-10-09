"""Deterministic task factory: turns (task index, agent workload, rng) into a
``Task`` with a reference answer and, where relevant, ground-truth documents
and expected tool calls."""

from __future__ import annotations

import random

from common.ids import stable_id
from generator.agents.base import Task
from generator.agents.corpus import (
    BENIGN_NEAR_MISS_INPUTS,
    INJECTION_BAIT,
    INJECTION_INPUTS,
    QA_BANK,
    TICKET_ISSUES,
    order_status,
)

BENIGN_NEAR_MISS_RATE = 0.03


def _fmt_number(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.4f}".rstrip("0").rstrip(".")


def _qa_like(index: int, workload: str, rng: random.Random, faults: tuple[str, ...]) -> Task:
    if "prompt_injection" in faults and workload in ("rag", "multi_step"):
        item = rng.choice(INJECTION_BAIT)  # poisoned document will be retrieved
        user_input = item.question
    else:
        item = rng.choice(QA_BANK)
        user_input = item.question
        if "prompt_injection" in faults:
            user_input = f"{item.question} {rng.choice(INJECTION_INPUTS)}"
    benign = False
    if not faults and rng.random() < BENIGN_NEAR_MISS_RATE:
        user_input = f"{item.question} {rng.choice(BENIGN_NEAR_MISS_INPUTS)}"
        benign = True
    return Task(
        index=index,
        task_id=stable_id(workload, item.question, prefix="T-", n=12),
        workload_type=workload,
        difficulty=item.difficulty,
        user_input=user_input,
        reference_answer=item.answer,
        relevant_doc_ids=item.relevant_doc_ids,
        faults=faults,
        benign_near_miss=benign,
    )


def _tool_task(index: int, rng: random.Random, faults: tuple[str, ...]) -> Task:
    kind = rng.choices(("calc", "order", "ticket", "kb"), weights=(3, 3, 2, 2))[0]
    if kind == "calc":
        pct, base = rng.randint(5, 40), rng.randint(100, 9999)
        expr = f"{pct}/100*{base}"
        answer = _fmt_number(round(pct / 100 * base, 4))
        text, tools, difficulty = f"What is {pct}% of {base}?", (("calculator", {"expression": expr}),), "easy"
    elif kind == "order":
        oid = f"ORD-{rng.randint(1000, 99999)}"
        text, tools, difficulty = f"What is the status of order {oid}?", (("get_order_status", {"order_id": oid}),), "easy"
        answer = order_status(oid)
    elif kind == "ticket":
        issue, category, priority = rng.choice(TICKET_ISSUES)
        text = f"Open a {priority} priority {category} ticket: {issue}."
        tools = (("create_ticket", {"category": category, "priority": priority, "summary": issue}),)
        answer, difficulty = "ticket created", "medium"
    else:
        item = rng.choice(QA_BANK)
        text = f"Which knowledge-base document answers: {item.question}"
        tools = (("search_kb", {"query": item.question}),)
        answer, difficulty = item.relevant_doc_ids[0], "medium"
    if "prompt_injection" in faults:
        text = f"{text} {rng.choice(INJECTION_INPUTS)}"
    return Task(
        index=index,
        task_id=stable_id("tool", text, prefix="T-", n=12),
        workload_type="tool",
        difficulty=difficulty,
        user_input=text,
        reference_answer=answer,
        expected_tools=tools,
        faults=faults,
    )


def _multi_step_task(index: int, rng: random.Random, faults: tuple[str, ...]) -> Task:
    kind = rng.choice(("warranty", "error_ticket", "order_followup"))
    if kind == "warranty":
        product, months_total, doc = rng.choice((("NR-200", 24, "KB-001"), ("NR-500", 36, "KB-002")))
        bought = rng.randint(1, months_total - 1)
        text = f"A customer bought an {product} {bought} months ago. How many warranty months remain?"
        tools = (
            ("search_kb", {"query": f"{product} warranty policy"}),
            ("document_lookup", {"doc_id": doc}),
            ("calculator", {"expression": f"{months_total}-{bought}"}),
        )
        answer, rel, difficulty = str(months_total - bought), (doc,), "medium"
    elif kind == "error_ticket":
        code, doc, meaning = rng.choice((("E42", "KB-011", "joint encoder fault"), ("E17", "KB-012", "controller overheating")))
        text = f"Robot shows error {code}. Find what it means and open a high priority hardware ticket."
        tools = (
            ("search_kb", {"query": f"error code {code}"}),
            ("document_lookup", {"doc_id": doc}),
            ("create_ticket", {"category": "hardware", "priority": "high", "summary": f"Error {code}: {meaning}"}),
        )
        answer, rel, difficulty = meaning, (doc,), "hard"
    else:
        oid = f"ORD-{rng.randint(1000, 99999)}"
        status = order_status(oid)
        text = f"Check order {oid}; if it is on hold, open a medium priority billing ticket."
        tools = [("get_order_status", {"order_id": oid})]
        if status == "on_hold":
            tools.append(("create_ticket", {"category": "billing", "priority": "medium", "summary": f"Order {oid} on hold"}))
        tools_t = tuple(tools)
        return Task(
            index=index, task_id=stable_id("multi", text, prefix="T-", n=12), workload_type="multi_step",
            difficulty="medium", user_input=text + (f" {rng.choice(INJECTION_INPUTS)}" if "prompt_injection" in faults else ""),
            reference_answer=status, expected_tools=tools_t, faults=faults,
        )
    if "prompt_injection" in faults:
        text = f"{text} {rng.choice(INJECTION_INPUTS)}"
    return Task(
        index=index,
        task_id=stable_id("multi", text, prefix="T-", n=12),
        workload_type="multi_step",
        difficulty=difficulty,
        user_input=text,
        reference_answer=answer,
        relevant_doc_ids=rel,
        expected_tools=tools,
        faults=faults,
    )


def build_task(index: int, workload_type: str, rng: random.Random, faults: tuple[str, ...]) -> Task:
    if workload_type in ("qa", "rag"):
        return _qa_like(index, workload_type, rng, faults)
    if workload_type == "tool":
        return _tool_task(index, rng, faults)
    if workload_type == "multi_step":
        return _multi_step_task(index, rng, faults)
    raise ValueError(f"unknown workload_type {workload_type}")
