"""Sandboxed mock tools with structured JSON schemas.

None of these tools touch the shell, the filesystem or the network. Arguments
are validated against JSON Schema before execution. Dangerous tools
(``export_data``, ``execute_shell``, ...) exist only as *names* the policy
engine can deny; their "execution" is a no-op stub that returns nothing.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator

from common.ids import stable_id
from generator.agents.corpus import DOC_BY_ID, DOCUMENTS, order_status, tokenize


class ToolError(Exception):
    pass


_OPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def safe_calculate(expression: str) -> float:
    """Evaluate +-*/%** arithmetic over numeric literals only (no names, calls or attributes)."""
    if len(expression) > 120:
        raise ToolError("expression too long")

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            right = _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ToolError("exponent too large")
            return _OPS[type(node.op)](_eval(node.left), right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _eval(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        raise ToolError(f"unsupported expression element: {type(node).__name__}")

    try:
        return round(_eval(ast.parse(expression, mode="eval")), 4)
    except (SyntaxError, ZeroDivisionError) as exc:
        raise ToolError(str(exc)) from exc


def _search_kb(args: dict[str, Any]) -> dict[str, Any]:
    q = set(tokenize(args["query"]))
    scored = sorted(
        ((len(q & d.tokens) / (len(q) or 1), d.doc_id) for d in DOCUMENTS if d.classification != "restricted"),
        reverse=True,
    )
    return {"doc_ids": [doc_id for score, doc_id in scored[: args.get("limit", 3)] if score > 0]}


def _document_lookup(args: dict[str, Any]) -> dict[str, Any]:
    doc = DOC_BY_ID.get(args["doc_id"])
    if doc is None:
        raise ToolError(f"unknown document {args['doc_id']}")
    return {"doc_id": doc.doc_id, "title": doc.title, "classification": doc.classification, "text": doc.text}


def _calculator(args: dict[str, Any]) -> dict[str, Any]:
    return {"result": safe_calculate(args["expression"])}


def _get_order_status(args: dict[str, Any]) -> dict[str, Any]:
    return {"order_id": args["order_id"], "status": order_status(args["order_id"])}


def _create_ticket(args: dict[str, Any]) -> dict[str, Any]:
    return {"ticket_id": stable_id(args["category"], args["summary"], prefix="TCK-", n=8), "status": "open"}


def _delegate_subtask(args: dict[str, Any]) -> dict[str, Any]:
    return {"accepted": True, "subagent": args["subagent"]}


def _stub(args: dict[str, Any]) -> dict[str, Any]:
    # Disallowed/egress tools are never really executed.
    return {"executed": False}


_VALIDATORS: dict[str, Draft202012Validator] = {}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict[str, Any]
    fn: Callable[[dict[str, Any]], dict[str, Any]]
    data_classification: str = "public"

    def validate_args(self, args: dict[str, Any]) -> list[str]:
        validator = _VALIDATORS.get(self.name)
        if validator is None:
            validator = _VALIDATORS[self.name] = Draft202012Validator(self.schema)
        return [e.message for e in validator.iter_errors(args)]


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec("search_kb", _obj({"query": {"type": "string", "minLength": 3}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"]), _search_kb),
        ToolSpec("document_lookup", _obj({"doc_id": {"type": "string", "pattern": "^[A-Z]{2,3}-[0-9]{3}$"}}, ["doc_id"]), _document_lookup),
        ToolSpec("calculator", _obj({"expression": {"type": "string", "maxLength": 120}}, ["expression"]), _calculator),
        ToolSpec("get_order_status", _obj({"order_id": {"type": "string", "pattern": "^ORD-[0-9]{4,6}$"}}, ["order_id"]), _get_order_status, "internal"),
        ToolSpec(
            "create_ticket",
            _obj(
                {
                    "category": {"enum": ["hardware", "software", "training", "billing"]},
                    "priority": {"enum": ["low", "medium", "high"]},
                    "summary": {"type": "string", "minLength": 5, "maxLength": 200},
                },
                ["category", "priority", "summary"],
            ),
            _create_ticket,
            "internal",
        ),
        ToolSpec("delegate_subtask", _obj({"subagent": {"type": "string"}, "task": {"type": "string"}}, ["subagent", "task"]), _delegate_subtask),
        # Tools below exist so the policy engine can deny them; they never execute.
        ToolSpec("export_data", _obj({"target": {"type": "string"}}, ["target"]), _stub, "restricted"),
        ToolSpec("execute_shell", _obj({"command": {"type": "string"}}, ["command"]), _stub, "restricted"),
        ToolSpec("delete_records", _obj({"table": {"type": "string"}}, ["table"]), _stub, "restricted"),
        ToolSpec("modify_permissions", _obj({"role": {"type": "string"}}, ["role"]), _stub, "restricted"),
        ToolSpec("send_external_email", _obj({"to": {"type": "string"}, "body": {"type": "string"}}, ["to", "body"]), _stub, "public"),
        ToolSpec("http_post", _obj({"url": {"type": "string"}, "body": {"type": "string"}}, ["url", "body"]), _stub, "public"),
        ToolSpec("read_resource", _obj({"resource": {"type": "string"}}, ["resource"]), _stub, "restricted"),
    )
}


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(f"unknown tool {name}")
    errors = spec.validate_args(args)
    if errors:
        raise ToolError("invalid arguments: " + "; ".join(errors))
    return spec.fn(args)


# Structured output schema every agent's final answer must satisfy.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "citations": {"type": "array", "items": {"type": "string"}},
        "tool_results": {"type": "array"},
    },
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}
ANSWER_VALIDATOR = Draft202012Validator(ANSWER_SCHEMA)
