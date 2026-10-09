"""Known synthetic anomalies must trigger their rule; normal runs must not."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import rules
from ml.evaluate_detector import prf
from ml.features import FEATURES, Baseline

TH = {"latency_mad_k": 6.0, "tokens_mad_k": 6.0, "tool_latency_mad_k": 6.0, "min_baseline_runs": 30,
      "repeated_tool_calls": 5, "max_chain_spans": 30, "window_minutes": 15, "min_window_runs": 8,
      "window_p_value": 1e-5, "error_rate_abs": 0.15, "slow_share_abs": 0.4}


def normal_runs(n=400, seed=0, start="2026-10-09T00:00:00Z", agent="ops-tool-agent", version="1.0.0") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start)
    df = pd.DataFrame({
        "run_id": [f"R-{seed}-{i}" for i in range(n)],
        "trace_id": [f"{i:032x}" for i in range(n)],
        "agent_id": agent, "agent_version": version, "agent_name": "Ops", "test_run_id": "TR-x", "scenario_id": "s",
        "event_time": [t0 + pd.Timedelta(seconds=30 * i) for i in range(n)],
        "status": "completed",
        "latency_ms": rng.lognormal(np.log(1200), 0.25, n),
        "total_tokens": rng.normal(800, 60, n).round(),
        "output_tokens": rng.normal(120, 15, n).round(),
        "llm_calls": 2, "tool_calls": 1, "tool_errors": 0, "tool_timeouts": 0, "retries": 0,
        "span_count": 6, "max_depth": 2, "max_consecutive_same_tool": 1,
        "avg_tool_latency_ms": rng.lognormal(np.log(140), 0.3, n), "retrieval_count": 0, "is_failed": 0,
        "injected_faults": [[] for _ in range(n)],
    })
    df.loc[rng.random(n) < 0.04, "is_failed"] = 1
    return df


@pytest.fixture(scope="module")
def baseline():
    return Baseline.fit(normal_runs())


def detectors_for(df, baseline):
    return {d.detector for d in rules.run_rules(df, baseline, TH)}


def test_normal_traffic_has_no_per_run_alerts(baseline):
    dets = rules.run_rules(normal_runs(seed=1), baseline, TH)
    assert len(dets) <= 2  # robust 6-MAD thresholds: essentially silent on normal traffic


@pytest.mark.parametrize("change,expected", [
    ({"latency_ms": 60_000.0}, "rule:latency_spike"),
    ({"total_tokens": 9_000.0}, "rule:token_spike"),
    ({"avg_tool_latency_ms": 2_500.0}, "rule:tool_latency_spike"),
    ({"max_consecutive_same_tool": 9, "tool_calls": 10}, "rule:repeated_tool_calls"),
    ({"span_count": 45}, "rule:long_chain"),
    ({"tool_timeouts": 2, "retries": 2}, "rule:tool_timeout"),
])
def test_injected_anomaly_triggers_its_rule(baseline, change, expected):
    df = normal_runs(n=5, seed=2)
    for k, v in change.items():
        df.loc[2, k] = v
    found = {d.detector for d in rules.run_rules(df, baseline, TH) if d.run_index == 2}
    assert expected in found
    assert all(d.explanation for d in rules.run_rules(df, baseline, TH))


def test_unknown_agent_version_is_not_scored(baseline):
    df = normal_runs(n=5, seed=3, version="9.9.9")
    df.loc[0, "latency_ms"] = 1e7
    assert rules.run_rules(df, baseline, TH) == []


def test_window_error_spike_detected_and_normal_window_silent(baseline):
    df = normal_runs(n=60, seed=4, start="2026-10-09T10:00:00Z")
    df["event_time"] = [pd.Timestamp("2026-10-09T10:00:00Z") + pd.Timedelta(seconds=10 * i) for i in range(60)]
    assert [d for d in rules.window_rules(df.assign(is_failed=0), baseline, TH) if d.anomaly_type == "error_rate_spike"] == []
    spiky = df.copy()
    spiky.loc[spiky.index[:40:2], "is_failed"] = 1  # 20 failures inside the first windows
    hits = [d for d in rules.window_rules(spiky, baseline, TH) if d.anomaly_type == "error_rate_spike"]
    assert hits and hits[0].supporting["p_value"] < 1e-5 and hits[0].run_ids


def test_window_latency_regression(baseline):
    df = normal_runs(n=40, seed=5)
    df["event_time"] = [pd.Timestamp("2026-10-09T10:00:00Z") + pd.Timedelta(seconds=20 * i) for i in range(40)]
    df["latency_ms"] = df["latency_ms"] * 3
    hits = [d for d in rules.window_rules(df, baseline, TH) if d.anomaly_type == "latency_regression"]
    assert hits


def test_zscores_are_relative_to_own_version():
    a = normal_runs(seed=6, version="1.0.0")
    b = normal_runs(seed=7, version="2.0.0")
    b["latency_ms"] *= 5  # slower version, but normal for itself
    bl = Baseline.fit(pd.concat([a, b], ignore_index=True))
    z = bl.zscores(b)
    assert z["latency_ms"].abs().median() < 1.0
    assert set(FEATURES) <= set(z.columns)


def test_prf_metrics():
    m = prf(np.array([1, 1, 0, 0, 1]), np.array([1, 0, 0, 1, 1]))
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3, abs=1e-4) and m["recall"] == pytest.approx(2 / 3, abs=1e-4)
