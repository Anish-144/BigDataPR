"""Rule-based anomaly detection: immediate and explainable.

Per-run rules compare a run with the robust baseline of its own agent version
(median + k * MAD-scale, thresholds from config/thresholds.yaml). Window rules
look for sudden error/timeout-rate increases per agent version.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import binom

from common.config import load_thresholds
from ml.features import Baseline

RULES_VERSION = "rules-2.0"


@dataclass
class Detection:
    detector: str
    anomaly_type: str
    severity: str
    score: float
    explanation: str
    supporting: dict[str, float] = field(default_factory=dict)
    run_index: int | None = None  # dataframe index for per-run detections
    window_start: pd.Timestamp | None = None
    window_end: pd.Timestamp | None = None
    agent_id: str | None = None
    agent_version: str | None = None
    run_ids: list[str] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)


def _sev(z: float) -> str:
    return "critical" if z >= 30 else "high" if z >= 15 else "medium" if z >= 8 else "low"


def run_rules(df: pd.DataFrame, baseline: Baseline, th: dict | None = None) -> list[Detection]:
    th = th or load_thresholds()["anomaly_rules"]
    z = baseline.zscores(df)
    out: list[Detection] = []
    for idx, row in df.iterrows():
        st = baseline.stats.get(Baseline.key(row.agent_id, row.agent_version))
        if st is None or st["latency_ms"]["n"] < th["min_baseline_runs"]:
            continue
        who = f"{row.agent_id} {row.agent_version}"
        zl, zt = z.at[idx, "latency_ms"], z.at[idx, "total_tokens"]
        if zl >= th["latency_mad_k"]:
            out.append(Detection("rule:latency_spike", "latency_spike", _sev(zl), round(float(zl), 3),
                                 f"latency {row.latency_ms:.0f} ms is {zl:.1f} robust SDs above the {who} baseline "
                                 f"(median {st['latency_ms']['raw_median']:.0f} ms)",
                                 {"latency_ms": float(row.latency_ms), "baseline_median_ms": st["latency_ms"]["raw_median"], "z": float(zl)},
                                 run_index=idx))
        if zt >= th["tokens_mad_k"]:
            out.append(Detection("rule:token_spike", "token_cost_spike", _sev(zt), round(float(zt), 3),
                                 f"{row.total_tokens:.0f} tokens is {zt:.1f} robust SDs above the {who} baseline "
                                 f"(median {st['total_tokens']['raw_median']:.0f})",
                                 {"total_tokens": float(row.total_tokens), "baseline_median": st["total_tokens"]["raw_median"], "z": float(zt)},
                                 run_index=idx))
        za = z.at[idx, "avg_tool_latency_ms"]
        if row.tool_calls > 0 and za >= th["tool_latency_mad_k"]:
            out.append(Detection("rule:tool_latency_spike", "slow_tool_call", _sev(za), round(float(za), 3),
                                 f"average tool latency {row.avg_tool_latency_ms:.0f} ms is {za:.1f} robust SDs above the {who} "
                                 f"baseline (median {st['avg_tool_latency_ms']['raw_median']:.0f} ms)",
                                 {"avg_tool_latency_ms": float(row.avg_tool_latency_ms),
                                  "baseline_median_ms": st["avg_tool_latency_ms"]["raw_median"], "z": float(za)}, run_index=idx))
        if row.max_consecutive_same_tool >= th["repeated_tool_calls"]:
            n = int(row.max_consecutive_same_tool)
            out.append(Detection("rule:repeated_tool_calls", "suspected_loop", "high" if n >= 8 else "medium", float(n),
                                 f"same tool called {n} times in a row (threshold {th['repeated_tool_calls']}) - suspected loop",
                                 {"max_consecutive_same_tool": float(n), "tool_calls": float(row.tool_calls)}, run_index=idx))
        if row.span_count > th["max_chain_spans"]:
            out.append(Detection("rule:long_chain", "long_execution_chain", "medium", float(row.span_count),
                                 f"{int(row.span_count)} spans in one run (threshold {th['max_chain_spans']})",
                                 {"span_count": float(row.span_count)}, run_index=idx))
        if row.tool_timeouts >= 1:
            out.append(Detection("rule:tool_timeout", "tool_timeout", "high" if row.tool_timeouts >= 3 else "medium",
                                 float(row.tool_timeouts),
                                 f"{int(row.tool_timeouts)} tool call(s) hit the timeout; run status {row.status}",
                                 {"tool_timeouts": float(row.tool_timeouts), "retries": float(row.retries)}, run_index=idx))
    return out


def window_rules(df: pd.DataFrame, baseline: Baseline, th: dict | None = None) -> list[Detection]:
    """Per agent version and fixed window, test whether failures or slow runs are significantly more frequent
    than in the reference profile (one-sided binomial tail; p < window_p_value)."""
    th = th or load_thresholds()["anomaly_rules"]
    if df.empty:
        return []
    width = pd.Timedelta(minutes=th["window_minutes"])
    out: list[Detection] = []
    d = df.assign(window=df["event_time"].dt.floor(width))
    for (aid, ver, w), g in d.groupby(["agent_id", "agent_version", "window"]):
        ref = baseline.stats.get(Baseline.key(aid, ver), {}).get("__window__")
        n = len(g)
        if ref is None or n < th["min_window_runs"]:
            continue
        # error / timeout rate vs the reference failure rate
        k = int(g["is_failed"].sum())
        p0 = max(ref["failure_rate"], 0.005)
        p_err = float(binom.sf(k - 1, n, p0)) if k else 1.0
        if k / n >= th["error_rate_abs"] and p_err < th["window_p_value"]:
            bad = g[g.is_failed == 1]
            out.append(Detection(
                "rule:window_error_rate", "error_rate_spike", "critical" if k / n >= 0.5 else "high",
                round(-math.log10(max(p_err, 1e-300)), 3),
                f"{k}/{n} runs failed or timed out in a {th['window_minutes']}-minute window for {aid} {ver} "
                f"(baseline {p0:.1%}; binomial p={p_err:.2g})",
                {"window_error_rate": k / n, "baseline_error_rate": p0, "runs_in_window": float(n), "p_value": p_err},
                window_start=w, window_end=w + width, agent_id=aid, agent_version=ver,
                run_ids=list(bad.run_id)[:50], trace_ids=list(bad.trace_id)[:50]))
        # latency regression: share of runs slower than the reference p90 (10% expected under no change)
        slow = g[g["latency_ms"] > ref["latency_p90"]]
        ks = len(slow)
        p_lat = float(binom.sf(ks - 1, n, 0.10)) if ks else 1.0
        if ks / n >= th["slow_share_abs"] and p_lat < th["window_p_value"]:
            out.append(Detection(
                "rule:window_latency_regression", "latency_regression", "high", round(-math.log10(max(p_lat, 1e-300)), 3),
                f"{ks}/{n} runs exceeded the reference p90 latency ({ref['latency_p90']:.0f} ms) in a "
                f"{th['window_minutes']}-minute window for {aid} {ver} (expected 10%; binomial p={p_lat:.2g}); "
                f"window median {g['latency_ms'].median():.0f} ms",
                {"slow_share": ks / n, "reference_p90_ms": ref["latency_p90"],
                 "window_median_ms": float(g["latency_ms"].median()), "runs_in_window": float(n), "p_value": p_lat},
                window_start=w, window_end=w + width, agent_id=aid, agent_version=ver,
                run_ids=list(slow.run_id)[:50], trace_ids=list(slow.trace_id)[:50]))
    return out
