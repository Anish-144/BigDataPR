from __future__ import annotations

import pytest

from evaluation.regression_gate import Cohort, compare, two_proportion_p_value

TH = {
    "min_runs_per_cohort": 50,
    "success_rate_drop_pct_points": {"review": 2.0, "fail": 5.0},
    "p95_latency_increase_pct": {"review": 10.0, "fail": 25.0},
    "avg_tokens_increase_pct": {"review": 15.0, "fail": 40.0},
    "cost_per_success_increase_pct": {"review": 15.0, "fail": 40.0},
    "retrieval_recall_drop_pct_points": {"review": 3.0, "fail": 8.0},
    "security_findings_increase_per_1k_runs": {"review": 2.0, "fail": 10.0},
}


def cohort(version="1", runs=1000, success=0.9, p95=1000.0, tokens=500.0, cps=0.001, recall=None, f1k=0.0):
    return Cohort("a", version, runs, int(runs * success), success, p95, tokens, cps, recall, f1k)


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_identical_cohorts_pass():
    verdict, checks, p = compare(cohort(), cohort("2"), TH)
    assert verdict == "PASSED"
    assert statuses(checks)["retrieval_recall_drop"] == "skipped"
    assert p == pytest.approx(1.0)


def test_latency_review_and_fail_bounds():
    assert compare(cohort(), cohort("2", p95=1150.0), TH)[0] == "NEEDS_REVIEW"
    verdict, checks, _ = compare(cohort(), cohort("2", p95=1300.0), TH)
    assert verdict == "FAILED" and statuses(checks)["p95_latency_increase"] == "fail"


def test_improvements_never_fail():
    verdict, checks, _ = compare(cohort(), cohort("2", success=0.95, p95=800.0, tokens=400.0, cps=0.0005), TH)
    assert verdict == "PASSED"
    assert all(c.delta is None or c.status == "pass" for c in checks)


def test_retrieval_regression_detected():
    verdict, checks, _ = compare(cohort(recall=0.95), cohort("2", recall=0.85), TH)
    assert verdict == "FAILED" and statuses(checks)["retrieval_recall_drop"] == "fail"


def test_insufficient_data_overrides():
    assert compare(cohort(runs=20), cohort("2", runs=20, p95=5000.0), TH)[0] == "INSUFFICIENT_DATA"


def test_p_value_distinguishes_noise_from_signal():
    assert two_proportion_p_value(900, 1000, 890, 1000) > 0.05      # 1 pp on 1k runs: noise
    assert two_proportion_p_value(900, 1000, 820, 1000) < 0.001     # 8 pp on 1k runs: real
    assert two_proportion_p_value(0, 0, 1, 1) is None
