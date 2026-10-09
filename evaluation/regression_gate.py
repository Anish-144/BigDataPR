"""Regression gate: candidate agent version vs baseline, on lakehouse data.

Checks (thresholds in config/thresholds.yaml -> regression_gate):
  success-rate drop (pp), p95 latency increase (%), avg tokens increase (%),
  estimated cost per successful task increase (%), Recall@K drop (pp, RAG only),
  security findings per 1k runs increase.

Verdict: FAILED if any check breaches its fail bound, NEEDS_REVIEW if any
breaches its review bound, INSUFFICIENT_DATA if a cohort has fewer than
min_runs_per_cohort runs, else PASSED. The success-rate check also reports a
two-proportion z-test p-value so reviewers can tell noise from real change
(informational; the verdict uses the configured thresholds).

    python -m evaluation.regression_gate --all --scenario regression
    python -m evaluation.regression_gate --agent rag-helpdesk --baseline 2.0.0 --candidate 2.1.0
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from common.config import load_thresholds

T = "lakehouse.analytics"


@dataclass
class Cohort:
    agent_id: str
    version: str
    runs: int
    successes: int
    success_rate: float | None
    p95_latency_ms: float | None
    avg_tokens: float | None
    cost_per_success: float | None
    recall_at_k: float | None
    findings_per_1k: float | None


@dataclass
class Check:
    name: str
    unit: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    review: float
    fail: float
    status: str  # pass | review | fail | skipped
    note: str = ""


@dataclass
class GateResult:
    gate_id: str
    evaluated_at: str
    agent_id: str
    baseline: Cohort
    candidate: Cohort
    scenario_id: str | None
    test_run_id: str | None
    verdict: str
    checks: list[Check] = field(default_factory=list)
    success_rate_p_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def two_proportion_p_value(s1: int, n1: int, s2: int, n2: int) -> float | None:
    if min(n1, n2) == 0:
        return None
    p = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(s2 / n2 - s1 / n1) / se
    return round(2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))), 6)


def _pct_change(base: float | None, cand: float | None) -> float | None:
    if base is None or cand is None or base == 0:
        return None
    return 100.0 * (cand - base) / base


def _status(delta: float | None, review: float, fail: float) -> str:
    if delta is None:
        return "skipped"
    if delta >= fail:
        return "fail"
    if delta >= review:
        return "review"
    return "pass"


def compare(base: Cohort, cand: Cohort, thresholds: dict[str, Any] | None = None) -> tuple[str, list[Check], float | None]:
    """Pure comparison logic (unit-tested without a database)."""
    th = thresholds or load_thresholds()["regression_gate"]
    checks: list[Check] = []

    def add(name: str, unit: str, b, c, delta, key: str, note: str = "") -> None:
        bounds = th[key]
        checks.append(Check(name, unit, b, c, None if delta is None else round(delta, 4),
                            bounds["review"], bounds["fail"], _status(delta, bounds["review"], bounds["fail"]), note))

    drop_pp = None if base.success_rate is None or cand.success_rate is None else 100.0 * (base.success_rate - cand.success_rate)
    p_value = two_proportion_p_value(base.successes, base.runs, cand.successes, cand.runs)
    add("success_rate_drop", "percentage points", base.success_rate, cand.success_rate, drop_pp,
        "success_rate_drop_pct_points", f"two-proportion z-test p={p_value:.3g}" if p_value is not None else "")
    add("p95_latency_increase", "%", base.p95_latency_ms, cand.p95_latency_ms,
        _pct_change(base.p95_latency_ms, cand.p95_latency_ms), "p95_latency_increase_pct")
    add("avg_tokens_increase", "%", base.avg_tokens, cand.avg_tokens,
        _pct_change(base.avg_tokens, cand.avg_tokens), "avg_tokens_increase_pct")
    add("cost_per_success_increase", "%", base.cost_per_success, cand.cost_per_success,
        _pct_change(base.cost_per_success, cand.cost_per_success), "cost_per_success_increase_pct",
        "estimated cost (config/pricing.yaml)")
    recall_drop = (None if base.recall_at_k is None or cand.recall_at_k is None
                   else 100.0 * (base.recall_at_k - cand.recall_at_k))
    add("retrieval_recall_drop", "percentage points", base.recall_at_k, cand.recall_at_k, recall_drop,
        "retrieval_recall_drop_pct_points", "" if recall_drop is not None else "no retrieval metrics for this agent")
    sec_delta = (None if base.findings_per_1k is None or cand.findings_per_1k is None
                 else cand.findings_per_1k - base.findings_per_1k)
    add("security_findings_increase", "findings per 1k runs", base.findings_per_1k, cand.findings_per_1k, sec_delta,
        "security_findings_increase_per_1k_runs")

    if min(base.runs, cand.runs) < th["min_runs_per_cohort"]:
        verdict = "INSUFFICIENT_DATA"
    elif any(c.status == "fail" for c in checks):
        verdict = "FAILED"
    elif any(c.status == "review" for c in checks):
        verdict = "NEEDS_REVIEW"
    else:
        verdict = "PASSED"
    return verdict, checks, p_value


# --------------------------------------------------------------------------- lakehouse access

COHORT_SQL = f"""
WITH runs AS (
    SELECT * FROM (
        SELECT m.*, row_number() OVER (PARTITION BY m.run_id ORDER BY m.ingested_at) AS rn  -- de-duplicate replays
        FROM {T}.agent_run_metrics m
        WHERE m.agent_id = ? AND m.agent_version = ?
          AND m.event_date >= current_date - (? * INTERVAL '1' DAY)
          AND (? = '' OR m.scenario_id = ?)
          AND (? = '' OR m.test_run_id = ?)
    ) WHERE rn = 1
),
findings AS (
    SELECT count(*) AS n FROM {T}.agent_security_findings f WHERE f.run_id IN (SELECT run_id FROM runs)
),
recall AS (
    SELECT avg(score) AS r FROM {T}.agent_evaluation_results e
    WHERE e.metric_name = 'recall_at_k' AND e.evaluator_type = 'deterministic' AND e.run_id IN (SELECT run_id FROM runs)
)
SELECT count(*), count_if(task_success), avg(IF(task_success, 1e0, 0e0)), approx_percentile(latency_ms, 0.95),
       avg(total_tokens), sum(estimated_cost_usd) / nullif(count_if(task_success), 0),
       (SELECT r FROM recall), 1000e0 * (SELECT n FROM findings) / nullif(count(*), 0)
FROM runs
"""


def fetch_cohort(agent_id: str, version: str, days: int, scenario: str | None, test_run_id: str | None) -> Cohort:
    from lakehouse.trino_client import run_query

    s, t = scenario or "", test_run_id or ""
    row = run_query(COHORT_SQL, [agent_id, version, days, s, s, t, t]).rows[0]
    return Cohort(agent_id, version, int(row[0]), int(row[1] or 0), row[2], row[3], row[4], row[5], row[6], row[7])


def version_pairs() -> list[tuple[str, str, str]]:
    """(agent_id, baseline_version, candidate_version) from the registry: lowest vs highest release_seq."""
    from lakehouse.trino_client import run_query

    rows = run_query(f"""
        SELECT agent_id, max_by(agent_version, -release_seq), max_by(agent_version, release_seq)
        FROM {T}.agent_registry GROUP BY agent_id HAVING count(*) >= 2 ORDER BY agent_id""").rows
    return [(r[0], r[1], r[2]) for r in rows]


def persist(result: GateResult) -> None:
    from lakehouse.trino_client import connect

    conn = connect()
    cur = conn.cursor()
    thresholds_version = "config/thresholds.yaml"
    for c in result.checks:
        cur.execute(
            f"INSERT INTO {T}.agent_regression_results VALUES (?, from_iso8601_timestamp(?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [result.gate_id, result.evaluated_at, result.agent_id, result.baseline.version, result.candidate.version,
             result.scenario_id, result.test_run_id, c.name, c.unit,
             None if c.baseline is None else float(c.baseline), None if c.candidate is None else float(c.candidate),
             c.delta, float(c.review), float(c.fail), c.status, result.verdict, result.baseline.runs,
             result.candidate.runs, result.success_rate_p_value, c.note, thresholds_version],
        )
        cur.fetchall()
    conn.close()


def run_gate(agent_id: str, baseline: str, candidate: str, days: int = 30, scenario: str | None = None,
             test_run_id: str | None = None, save: bool = True) -> GateResult:
    b = fetch_cohort(agent_id, baseline, days, scenario, test_run_id)
    c = fetch_cohort(agent_id, candidate, days, scenario, test_run_id)
    verdict, checks, p = compare(b, c)
    result = GateResult(
        gate_id=f"G-{uuid.uuid4().hex[:12]}", evaluated_at=datetime.now(timezone.utc).isoformat(), agent_id=agent_id,
        baseline=b, candidate=c, scenario_id=scenario, test_run_id=test_run_id, verdict=verdict, checks=checks,
        success_rate_p_value=p,
    )
    if save:
        persist(result)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent")
    ap.add_argument("--baseline")
    ap.add_argument("--candidate")
    ap.add_argument("--all", action="store_true", help="every agent: lowest vs highest release_seq")
    ap.add_argument("--scenario")
    ap.add_argument("--test-run-id")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)
    pairs = version_pairs() if args.all else [(args.agent, args.baseline, args.candidate)]
    if not all(all(p) for p in pairs):
        ap.error("give --all or --agent/--baseline/--candidate")
    worst = 0
    for agent, base, cand in pairs:
        r = run_gate(agent, base, cand, args.days, args.scenario, args.test_run_id, save=not args.no_save)
        print(f"\n{agent}: {base} -> {cand}  verdict={r.verdict}  runs={r.baseline.runs}/{r.candidate.runs}  gate_id={r.gate_id}")
        for c in r.checks:
            fmt = lambda v: "-" if v is None else f"{v:.4g}"  # noqa: E731
            print(f"  [{c.status:7s}] {c.name:28s} base={fmt(c.baseline):>10} cand={fmt(c.candidate):>10} "
                  f"delta={fmt(c.delta):>8} {c.unit} (review>={c.review}, fail>={c.fail}) {c.note}")
        worst = max(worst, {"PASSED": 0, "NEEDS_REVIEW": 1, "INSUFFICIENT_DATA": 1, "FAILED": 2}[r.verdict])
    return worst


if __name__ == "__main__":
    sys.exit(main())
