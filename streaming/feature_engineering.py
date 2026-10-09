"""Row-level enrichment, derived features and data-quality flags (PySpark)."""

from __future__ import annotations

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F


def future_tolerance() -> Column:
    """Events stamped more than one day after ingestion are flagged (clock skew)."""
    return F.expr("INTERVAL 1 DAY")


def ts(col: str | Column) -> Column:
    """Cast an ISO-8601 string to timestamp (NULL when unparseable)."""
    c = F.col(col) if isinstance(col, str) else col
    return c.cast("timestamp")


def dq_flags(*pairs: tuple[Column, str]) -> Column:
    """Array of flag names whose condition is true (NULL conditions are ignored)."""
    return F.array_compact(F.array(*[F.when(cond, F.lit(name)) for cond, name in pairs]))


def span_features(df: DataFrame) -> DataFrame:
    return df.withColumn(
        "dq_flags",
        dq_flags(
            (F.col("duration_ms") < 0, "negative_duration"),
            (F.col("end_time") < F.col("start_time"), "end_before_start"),
            (F.col("event_time") > F.col("ingested_at") + future_tolerance(), "future_event_time"),
            (F.col("parent_span_id").isNull() & (F.col("span_kind") != "agent"), "missing_parent_id"),
        ),
    ).withColumn("depth", F.col("attributes").getItem("depth").cast("int"))


def run_features(df: DataFrame) -> DataFrame:
    """Derived per-run features used by analytics and the anomaly detector."""
    return (
        df.withColumn("total_tokens", F.col("input_tokens") + F.col("output_tokens"))
        .withColumn(
            "tokens_per_second",
            F.when(F.col("latency_ms") > 0, F.col("output_tokens") / (F.col("latency_ms") / 1000.0)),
        )
        .withColumn(
            "tool_error_rate",
            F.when(F.col("tool_calls") > 0, (F.col("tool_errors") + F.col("tool_timeouts")) / F.col("tool_calls")),
        )
        .withColumn(
            "dq_flags",
            dq_flags(
                (F.col("latency_ms") < 0, "negative_latency"),
                (F.col("end_time") < F.col("start_time"), "end_before_start"),
                (F.col("event_time") > F.col("ingested_at") + future_tolerance(), "future_event_time"),
                (F.col("estimated_cost_usd").isNull(), "cost_unavailable"),
            ),
        )
    )
