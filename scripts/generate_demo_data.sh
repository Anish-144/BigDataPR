#!/usr/bin/env bash
# Loads the standard, reproducible demo dataset (fixed seeds) into the pipeline,
# waits for Spark to land it in the lakehouse, then refreshes summary tables.
#
#   scripts/generate_demo_data.sh            # baseline + regression + fault + security suites (~0.75M events)
#   scripts/generate_demo_data.sh --small    # smoke scenario only (~5k events)
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

if [[ "${1:-}" == "--small" ]]; then
  scenarios=(smoke)
else
  scenarios=(baseline regression_v1_v2 fault_injection security_suite)
fi

for s in "${scenarios[@]}"; do
  echo "==> producing scenario: $s"
  $PY -m generator.producer --scenario "generator/scenarios/$s.yaml" | grep -E '"(test_run_id|status|tasks_completed|events_emitted|events_per_sec)"'
done

echo "==> waiting for the stream processor to drain Kafka into the lakehouse"
$PY -m lakehouse.wait_for_ingest --timeout 900

echo "==> refreshing summary tables"
$PY -m lakehouse.run_sql sql/07_summary_tables.sql --quiet
echo "done. Explore: python -m lakehouse.run_sql sql/02_performance_analytics.sql"
