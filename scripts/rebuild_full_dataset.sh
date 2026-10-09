#!/usr/bin/env bash
# Rebuild the complete reference dataset and every measured result from scratch.
# DESTRUCTIVE (resets Kafka topics, lakehouse tables and Spark checkpoints). Takes ~30 minutes.
#
#   scripts/rebuild_full_dataset.sh --yes            # standard data + detectors + gates + 1M/5M benchmarks
#   scripts/rebuild_full_dataset.sh --yes --no-5m    # skip the 5M-event benchmark
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh
[[ "${1:-}" == "--yes" ]] || { echo "usage: $0 --yes [--no-5m]   (destructive)"; exit 1; }
step() { echo; echo "==> [$(date +%H:%M:%S)] $*"; }

step "reset"
bash scripts/reset_demo.sh --yes
sleep 20

step "standard scenarios (baseline, regression, fault_injection, security_suite)"
bash scripts/generate_demo_data.sh

step "held-out labelled anomaly scenario"
$PY -m generator.producer --scenario generator/scenarios/fault_injection_holdout.yaml | grep -E '"(test_run_id|events_emitted)"'
$PY -m lakehouse.wait_for_ingest --timeout 900

step "train Isolation Forest (unlabelled baseline + regression), evaluate dev and holdout"
$PY -m ml.train_anomaly_model --scenarios baseline regression | grep -E '"model_version"|"runs"'
$PY -m ml.evaluate_detector --eval-scenario fault_injection | head -12
$PY -m ml.evaluate_detector --eval-scenario fault_injection_holdout | head -12

step "score all runs and publish alerts through Kafka"
$PY -m ml.score_events | grep -E '"(runs_scored|alerts|published)"'

step "regression gates (clean A/B suite)"
$PY -m evaluation.regression_gate --all --scenario regression | grep verdict || true

step "1M-event pipeline benchmark"
$PY -m benchmarks.pipeline_benchmark --events 1000000 --workers 6 | tail -22
if [[ "${2:-}" != "--no-5m" ]]; then
  step "5M-event pipeline benchmark"
  $PY -m benchmarks.pipeline_benchmark --events 5000000 --workers 6 --timeout 5400 | tail -22
fi

step "summary tables, SQL benchmark, SQL showcase export, generated docs"
$PY -m lakehouse.run_sql sql/07_summary_tables.sql --quiet
$PY -m benchmarks.sql_benchmark --runs 5
rm -rf docs/sql_outputs
$PY -m lakehouse.run_sql "sql/0[2-9]*.sql" --quiet --export docs/sql_outputs
$PY -m docs.generate_docs
step "done"
