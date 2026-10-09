#!/usr/bin/env bash
# Measured benchmarks. Results land in benchmarks/results/ (JSON + markdown).
#   scripts/run_benchmark.sh                  # 1M-event pipeline benchmark + SQL benchmark
#   scripts/run_benchmark.sh 5000000          # 5M events
#   scripts/run_benchmark.sh 100000 sql-only  # skip the pipeline run
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh
EVENTS=${1:-1000000}

if [[ "${2:-}" != "sql-only" ]]; then
  echo "==> pipeline benchmark: ${EVENTS} events"
  $PY -m benchmarks.pipeline_benchmark --events "$EVENTS" --workers 6
fi
echo "==> refreshing summary tables"
$PY -m lakehouse.run_sql sql/07_summary_tables.sql --quiet
echo "==> SQL benchmark (tiers, pruning, layout)"
$PY -m benchmarks.sql_benchmark --runs 5
