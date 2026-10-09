"""Per-run feature extraction (Trino -> pandas) and robust per-version baselines.

Ground-truth labels (injected_faults) are fetched only for evaluation and are
never part of the feature matrix.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lakehouse.trino_client import run_query

T = "lakehouse.analytics"

# Performance/behaviour features. Security signals (policy denials) are left to the security rules.
FEATURES = [
    "latency_ms", "total_tokens", "output_tokens", "llm_calls", "tool_calls", "tool_errors", "tool_timeouts",
    "retries", "span_count", "max_depth", "max_consecutive_same_tool", "avg_tool_latency_ms", "retrieval_count",
    "is_failed",
]
LOG_FEATURES = {"latency_ms", "total_tokens", "output_tokens", "avg_tool_latency_ms"}
PERFORMANCE_FAULTS = ("slow_tool", "tool_timeout", "loop", "malformed_response", "high_token_usage", "failed_retrieval")


def fetch_runs(test_run_ids: list[str] | None = None, scenarios: list[str] | None = None, days: int = 60,
               since_iso: str | None = None) -> pd.DataFrame:
    """De-duplicated run facts for the given scope (all filters are bound parameters)."""
    where = ["event_date >= current_date - (? * INTERVAL '1' DAY)"]
    params: list = [days]
    if test_run_ids:
        where.append(f"test_run_id IN ({', '.join('?' * len(test_run_ids))})")
        params += test_run_ids
    if scenarios:
        where.append(f"scenario_id IN ({', '.join('?' * len(scenarios))})")
        params += scenarios
    if since_iso:
        where.append("ingested_at >= from_iso8601_timestamp(?)")
        params.append(since_iso)
    sql = f"""
        SELECT run_id, trace_id, test_run_id, scenario_id, agent_id, agent_name, agent_version, event_time, status,
               error_category, latency_ms, total_tokens, output_tokens, llm_calls, tool_calls, tool_errors, tool_timeouts,
               retries, span_count, max_depth, max_consecutive_same_tool, coalesce(avg_tool_latency_ms, 0) AS avg_tool_latency_ms,
               retrieval_count, IF(status <> 'completed', 1, 0) AS is_failed, injected_faults
        FROM (
            SELECT *, row_number() OVER (PARTITION BY run_id ORDER BY ingested_at) AS rn
            FROM {T}.agent_run_metrics WHERE {' AND '.join(where)}
        ) WHERE rn = 1"""
    res = run_query(sql, params, max_rows=None)
    df = pd.DataFrame(res.rows, columns=res.columns)
    if df.empty:
        return df
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
    df["injected_faults"] = df["injected_faults"].apply(lambda x: list(x) if x is not None else [])
    for f in FEATURES:
        df[f] = pd.to_numeric(df[f], errors="coerce").fillna(0.0)
    return df


def labels(df: pd.DataFrame) -> pd.Series:
    """Ground truth for evaluation: a performance fault or an incident window was injected."""
    return df["injected_faults"].apply(
        lambda fs: any(f in PERFORMANCE_FAULTS or f.startswith("incident:") for f in fs)).astype(int)


@dataclass
class Baseline:
    """Robust per-(agent_id, agent_version) location/scale for every feature."""
    stats: dict[str, dict[str, dict[str, float]]]  # key -> feature -> {median, scale, n}

    @staticmethod
    def key(agent_id: str, version: str) -> str:
        return f"{agent_id}@{version}"

    @classmethod
    def fit(cls, df: pd.DataFrame) -> "Baseline":
        stats: dict = {}
        for (aid, ver), g in df.groupby(["agent_id", "agent_version"]):
            per = {}
            for f in FEATURES:
                x = transform(f, g[f].to_numpy(dtype=float))
                med = float(np.median(x))
                mad = float(np.median(np.abs(x - med))) * 1.4826
                scale = mad if mad > 1e-9 else float(np.std(x))
                per[f] = {"median": med, "scale": scale if scale > 1e-9 else 1.0, "n": int(len(x)),
                          "raw_median": float(np.median(g[f]))}
            per["__window__"] = {"failure_rate": float(g["is_failed"].mean()),
                                 "latency_p90": float(np.quantile(g["latency_ms"], 0.9)), "runs": int(len(g))}
            stats[cls.key(aid, ver)] = per
        return cls(stats)

    def zscores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Robust z-score of each feature relative to the run's own agent version (NaN if no baseline)."""
        out = pd.DataFrame(index=df.index, columns=FEATURES, dtype=float)
        for (aid, ver), g in df.groupby(["agent_id", "agent_version"]):
            st = self.stats.get(self.key(aid, ver))
            if st is None:
                continue
            for f in FEATURES:
                x = transform(f, g[f].to_numpy(dtype=float))
                out.loc[g.index, f] = (x - st[f]["median"]) / st[f]["scale"]
        return out

    def to_json(self) -> dict:
        return self.stats

    @classmethod
    def from_json(cls, data: dict) -> "Baseline":
        return cls(data)


def transform(feature: str, x: np.ndarray) -> np.ndarray:
    return np.log1p(np.maximum(x, 0)) if feature in LOG_FEATURES else x
