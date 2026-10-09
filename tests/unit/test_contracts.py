"""Contract tests: the Pydantic event models, the Spark wire DDL and the Trino
table DDL must agree, so no module can silently invent incompatible fields."""

from __future__ import annotations

import re
import types
import typing
from datetime import datetime
from enum import Enum
from pathlib import Path

import pytest

from generator import event_schema as es
from lakehouse.sql_catalog import load_file
from streaming import schemas

ROOT = Path(__file__).resolve().parents[2]

PAYLOAD_MODELS = {
    "test_run": es.TestRunPayload,
    "span.completed": es.SpanPayload,
    "run.metrics": es.RunMetricsPayload,
    "worker.resource": es.WorkerResourcePayload,
    "evaluation.result": es.EvaluationPayload,
    "security.finding": es.SecurityFindingPayload,
    "anomaly.alert": es.AnomalyAlertPayload,
}


def spark_type(annotation) -> str:
    """Map a Pydantic field annotation to the expected Spark wire type."""
    origin = typing.get_origin(annotation)
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if origin in (typing.Union, types.UnionType):
        assert len(args) == 1, annotation
        return spark_type(args[0])
    if origin is typing.Literal:
        return "STRING"
    if origin is list:
        return f"ARRAY<{spark_type(args[0])}>"
    if origin is dict:
        return f"MAP<{spark_type(args[0])},{spark_type(args[1])}>"
    if isinstance(annotation, type):
        if issubclass(annotation, Enum) or annotation is str:
            return "STRING"
        if annotation is bool:
            return "BOOLEAN"
        if annotation is int:
            return "BIGINT"
        if annotation is float:
            return "DOUBLE"
        if annotation is datetime:
            return "STRING"  # parsed explicitly so bad values can be quarantined
    raise AssertionError(f"unmapped annotation {annotation!r}")


@pytest.mark.parametrize("key,model", sorted(PAYLOAD_MODELS.items()))
def test_spark_payload_ddl_matches_pydantic(key, model):
    ddl = dict(schemas.ddl_fields(schemas.PAYLOAD_DDL[key]))
    expected = {name: spark_type(f.annotation) for name, f in model.model_fields.items()}
    assert ddl == expected


def test_envelope_ddl_matches_pydantic():
    ddl = dict(schemas.ddl_fields(schemas.ENVELOPE_DDL))
    base = es._EnvelopeBase.model_fields
    expected = {name: spark_type(f.annotation) for name, f in base.items()}
    expected["event_type"] = "STRING"
    expected["payload"] = "STRING"  # raw JSON object, parsed per event type
    assert ddl == expected


def test_event_type_routing_is_consistent():
    assert {k.value: v.value for k, v in es.EVENT_TOPIC.items()} == schemas.EVENT_TOPIC
    assert set(schemas.EVENT_PAYLOAD) == {t.value for t in es.EventType}
    assert {k.value: v for k, v in es.REQUIRED_CONTEXT.items()} == schemas.REQUIRED_CONTEXT
    assert tuple(es.SUPPORTED_SCHEMA_VERSIONS) == schemas.SUPPORTED_SCHEMA_VERSIONS


def test_required_payload_fields_exist():
    for key, fields in schemas.REQUIRED_PAYLOAD.items():
        names = set(PAYLOAD_MODELS[key].model_fields)
        assert set(fields) <= names, key
    for key, fields in schemas.TIMESTAMP_FIELDS.items():
        model = PAYLOAD_MODELS[key]
        assert {n for n, f in model.model_fields.items() if spark_type(f.annotation) == "STRING"
                and "datetime" in repr(f.annotation)} == set(fields), key


def trino_columns() -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for st in load_file(ROOT / "sql" / "01_schema_and_tables.sql"):
        m = re.match(r"CREATE TABLE IF NOT EXISTS lakehouse\.analytics\.(\w+)\s*\((.*)\)\s*WITH", st.sql, re.S)
        if not m:
            continue
        cols = []
        for line in m.group(2).splitlines():
            line = line.split("--")[0].strip()
            if line:
                cols.append(line.split()[0])
        tables[m.group(1)] = cols
    return tables


def test_curated_tables_cover_contract_fields():
    """Every payload field either lands in its curated table or is intentionally derived/omitted."""
    tables = trino_columns()
    mapping = {
        "agent_spans": ("span.completed", set()),
        "agent_run_metrics": ("run.metrics", {"routing_strategy"}),  # added by the schema-evolution demo
        "agent_evaluation_results": ("evaluation.result", set()),
        "agent_security_findings": ("security.finding", set()),
        "agent_anomaly_alerts": ("anomaly.alert", set()),
        "worker_resource_metrics": ("worker.resource", set()),
    }
    for table, (key, allowed_missing) in mapping.items():
        fields = {n for n, _ in schemas.ddl_fields(schemas.PAYLOAD_DDL[key])}
        missing = fields - set(tables[table]) - allowed_missing
        assert not missing, f"{table} missing {missing}"
        for shared in ("event_time", "event_date", "ingested_at", "batch_id"):
            assert shared in tables[table], (table, shared)


def test_fact_tables_carry_shared_keys():
    tables = trino_columns()
    for t in ("agent_spans", "agent_run_metrics", "agent_evaluation_results", "agent_security_findings", "agent_anomaly_alerts"):
        for key in ("test_run_id", "run_id", "trace_id", "agent_id", "agent_version", "scenario_id", "event_time", "event_date"):
            assert key in tables[t], (t, key)
