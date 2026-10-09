"""Task entry points for the Airflow DAGs (also runnable by hand).

Each command prints a JSON summary; commands whose result feeds a downstream
task print the value on the LAST line so Airflow's BashOperator can push it to
XCom (do_xcom_push uses the last line of stdout).

    python -m orchestration.tasks wait-ingest
    python -m orchestration.tasks regression-suite        # last line: test_run_id
    python -m orchestration.tasks regression-gate TR-20261009-abc123
    python -m orchestration.tasks train-and-evaluate
    python -m orchestration.tasks score-recent --minutes 1440
"""

from __future__ import annotations

import argparse
import json
import sys

from common.settings import REPO_ROOT


def wait_ingest(timeout: float) -> None:
    from lakehouse.wait_for_ingest import wait

    if not wait(timeout, quiet=False):
        raise SystemExit("lakehouse did not catch up with Kafka within the timeout")


def regression_suite(tasks: int | None) -> str:
    from generator.producer import run_test
    from generator.runner import TestRunConfig

    cfg = TestRunConfig.from_yaml(REPO_ROOT / "generator/scenarios/regression_v1_v2.yaml", triggered_by="airflow",
                                  tasks=tasks, notes="scheduled daily_agent_regression")
    summary = run_test(cfg, "kafka")
    print(json.dumps({k: summary[k] for k in ("test_run_id", "status", "tasks_completed", "events_emitted")}))
    if summary["status"] != "completed":
        raise SystemExit(f"regression suite did not complete: {summary['status']}")
    wait_ingest(1800)
    return summary["test_run_id"]


def regression_gate(test_run_id: str) -> int:
    from evaluation import regression_gate as rg

    worst = 0
    results = []
    for agent, base, cand in rg.version_pairs():
        r = rg.run_gate(agent, base, cand, days=30, scenario=None, test_run_id=test_run_id)
        results.append({"agent": agent, "baseline": base, "candidate": cand, "verdict": r.verdict, "gate_id": r.gate_id})
        worst = max(worst, {"PASSED": 0, "NEEDS_REVIEW": 1, "INSUFFICIENT_DATA": 1, "FAILED": 2}[r.verdict])
    print(json.dumps(results, indent=2))
    # Verdicts are recommendations for a human reviewer: the task succeeds and records them; it does not block.
    return worst


def train_and_evaluate() -> None:
    from ml.evaluate_detector import evaluate
    from ml.train_anomaly_model import train

    meta = train(["baseline", "regression"])
    res = evaluate("fault_injection_holdout", "security_suite")
    print(json.dumps({"model_version": meta["model_version"], "holdout": res["overall"]["combined"],
                      "roc_auc": res["isolation_forest_roc_auc"]}, indent=2))


def score_recent(minutes: int) -> None:
    from ml.score_events import score

    print(json.dumps(score(since_minutes=minutes), indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait-ingest")
    w.add_argument("--timeout", type=float, default=1800)
    s = sub.add_parser("regression-suite")
    s.add_argument("--tasks", type=int)
    g = sub.add_parser("regression-gate")
    g.add_argument("test_run_id")
    sub.add_parser("train-and-evaluate")
    sc = sub.add_parser("score-recent")
    sc.add_argument("--minutes", type=int, default=1440)
    a = ap.parse_args(argv)
    if a.cmd == "wait-ingest":
        wait_ingest(a.timeout)
    elif a.cmd == "regression-suite":
        print(regression_suite(a.tasks))  # last line -> XCom
    elif a.cmd == "regression-gate":
        regression_gate(a.test_run_id)
    elif a.cmd == "train-and-evaluate":
        train_and_evaluate()
    else:
        score_recent(a.minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
