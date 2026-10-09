"""Deterministic task evaluator.

Produces one ``EvalRecord`` per metric so evaluations land in the lakehouse in
long format (one row per run x metric). Every record carries the evaluator
name, version, type, rubric, threshold and evidence. All metrics here are
``deterministic``; model-judged scores (optional, see evaluation/llm_judge.py)
are stored with ``evaluator_type = model_judge`` and never mixed in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from evaluation import rag_metrics
from generator.agents.base import ExecutionResult, Task
from generator.agents.corpus import DOC_BY_ID, tokenize
from generator.agents.tools import ANSWER_VALIDATOR

EVALUATOR_VERSION = "1.0.0"
_PUNCT = re.compile(r"[^a-z0-9:\-\. ]+")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class EvalRecord:
    evaluator_name: str
    metric_name: str
    score: float | None
    passed: bool | None
    threshold: float | None
    rubric: str
    evidence: str
    evaluator_type: str = "deterministic"
    evaluator_version: str = EVALUATOR_VERSION


def normalize(text: str) -> str:
    return _SPACES.sub(" ", _PUNCT.sub(" ", text.lower())).strip().rstrip(".")


def answer_matches(answer: str, reference: str) -> bool:
    a, ref = normalize(answer), normalize(reference)
    if not a:
        return False
    if a == ref:
        return True
    # Reference contained in the answer, but only as whole tokens (so "24" does not match "124").
    return re.search(rf"(?<![\w.]){re.escape(ref)}(?![\w])", a) is not None


def token_f1(answer: str, reference: str) -> float:
    a, r = normalize(answer).split(), normalize(reference).split()
    if not a or not r:
        return 0.0
    common: dict[str, int] = {}
    for t in a:
        if t in r:
            common[t] = min(a.count(t), r.count(t))
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(a), overlap / len(r)
    return 2 * precision * recall / (precision + recall)


def parse_output(text: str) -> tuple[dict | None, list[str]]:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, [f"invalid JSON: {exc.msg if hasattr(exc, 'msg') else exc}"]
    errors = [e.message for e in ANSWER_VALIDATOR.iter_errors(obj)]
    return (obj if not errors else None), errors


def evaluate(task: Task, result: ExecutionResult) -> tuple[list[EvalRecord], bool]:
    """Evaluate one execution. Returns (records, task_success)."""
    records: list[EvalRecord] = []
    parsed, errors = parse_output(result.output_text)
    valid = parsed is not None
    records.append(
        EvalRecord(
            "structured_output_validator", "schema_validity", 1.0 if valid else 0.0, valid, 1.0,
            "Final output must be JSON that validates against ANSWER_SCHEMA",
            "valid" if valid else "; ".join(errors)[:200],
        )
    )

    answer = parsed["answer"] if parsed else ""
    match = valid and answer_matches(answer, task.reference_answer)
    records.append(
        EvalRecord(
            "reference_answer_match", "exact_match", 1.0 if match else 0.0, match, 1.0,
            "Normalised reference answer must appear as whole tokens in the agent answer",
            f"expected='{task.reference_answer}'" + ("" if match else " not found in answer"),
        )
    )
    f1 = token_f1(answer, task.reference_answer) if valid else 0.0
    records.append(
        EvalRecord("reference_answer_match", "token_f1", round(f1, 4), f1 >= 0.5, 0.5,
                   "Token-level F1 between normalised answer and reference", f"f1={f1:.3f}")
    )

    tools_ok = True
    if task.expected_tools:
        executed = [(c.tool_name, c.args) for c in result.tool_calls if c.status == "ok"]
        called = {c.tool_name for c in result.tool_calls if c.allowed}
        expected_names = [n for n, _ in task.expected_tools]
        selection = sum(1 for n in expected_names if n in called) / len(expected_names)
        args_ok = sum(1 for e in task.expected_tools if e in executed) / len(task.expected_tools)
        tools_ok = args_ok == 1.0
        records.append(
            EvalRecord("tool_call_checker", "tool_selection_accuracy", round(selection, 4), selection == 1.0, 1.0,
                       "Every expected tool must be called", f"expected={expected_names} called={sorted(called)}")
        )
        records.append(
            EvalRecord("tool_call_checker", "tool_argument_accuracy", round(args_ok, 4), tools_ok, 1.0,
                       "Every expected (tool, arguments) pair must execute successfully",
                       f"{int(args_ok * len(task.expected_tools))}/{len(task.expected_tools)} expected calls matched")
        )

    if task.relevant_doc_ids and task.workload_type in ("rag", "multi_step"):
        retrieved = [d for d, _ in result.retrieved]
        k = result.top_k or max(1, len(retrieved))
        rel = task.relevant_doc_ids
        recall = rag_metrics.recall_at_k(retrieved, rel, k)
        precision = rag_metrics.precision_at_k(retrieved, rel, k)
        rr = rag_metrics.reciprocal_rank(retrieved, rel)
        coverage = rag_metrics.citation_coverage(result.citations, retrieved, rel)
        evidence_tokens = [t for c in result.citations if c in DOC_BY_ID for t in tokenize(DOC_BY_ID[c].text)]
        grounded = rag_metrics.groundedness(tokenize(answer), evidence_tokens) if answer else 0.0
        hit = f"retrieved={retrieved[:k]} relevant={list(rel)}"
        records += [
            EvalRecord("retrieval_evaluator", "recall_at_k", round(recall, 4), recall >= 1.0, 1.0, f"Recall@{k} against ground-truth documents", hit),
            EvalRecord("retrieval_evaluator", "precision_at_k", round(precision, 4), None, None, f"Precision@{k} against ground-truth documents", hit),
            EvalRecord("retrieval_evaluator", "reciprocal_rank", round(rr, 4), rr > 0, None, "1/rank of first relevant document (averaged = MRR)", hit),
            EvalRecord("citation_checker", "citation_coverage", round(coverage, 4), coverage >= 1.0, 1.0,
                       "Relevant documents cited by the answer that were actually retrieved", f"citations={result.citations}"),
            EvalRecord("citation_checker", "groundedness", round(grounded, 4), grounded >= 0.5, 0.5,
                       "Share of answer tokens supported by cited document text (lexical proxy)", f"grounded={grounded:.3f}"),
        ]

    if valid:
        confident_wrong = (not match) and float(parsed.get("confidence", 0)) >= 0.7
        unsupported = rag_metrics.unsupported_citation_rate(result.citations, [d for d, _ in result.retrieved])
        flag = confident_wrong or unsupported > 0
        records.append(
            EvalRecord("hallucination_indicator", "hallucination_flag", 1.0 if flag else 0.0, not flag, 0.0,
                       "Flag when the answer is wrong with confidence >= 0.7 or cites unretrieved documents",
                       f"confident_wrong={confident_wrong} unsupported_citation_rate={unsupported:.2f}")
        )

    task_success = result.status == "completed" and valid and match and tools_ok
    return records, task_success
