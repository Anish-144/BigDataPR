#!/usr/bin/env bash
# DESTRUCTIVE: wipes all AgentShield event data (Kafka topics, Iceberg tables,
# Spark checkpoints) and recreates empty topics/tables. Postgres operational
# data (test-run requests, alert feedback) is kept unless --all is given.
#
#   scripts/reset_demo.sh          # asks for confirmation
#   scripts/reset_demo.sh --yes
#   scripts/reset_demo.sh --yes --all   # also wipes Postgres operational tables
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "This deletes all Kafka events, lakehouse tables and Spark checkpoints. Continue? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted"; exit 1; }
fi

echo "==> stopping stream processor"
docker compose stop spark-streaming

echo "==> deleting and recreating Kafka topics"
KT="docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"
for t in $($KT --list | grep '^agent-' || true); do
  $KT --delete --topic "$t"
done
for i in $(seq 1 30); do   # topic deletion is asynchronous: wait until it has really happened
  remaining=$($KT --list | grep -c '^agent-' || true)
  [[ "$remaining" == "0" ]] && break
  sleep 2
done
[[ "$remaining" == "0" ]] || { echo "Kafka topics were not deleted - aborting reset" >&2; exit 1; }
docker compose run --rm kafka-init

echo "==> dropping and recreating lakehouse tables"
$PY -m lakehouse.reset --yes

echo "==> clearing Spark checkpoints and progress state"
docker compose run --rm --no-deps --entrypoint bash spark-streaming -c 'rm -rf /opt/agentshield/checkpoints/* /opt/agentshield/state/*'

if [[ "${2:-}" == "--all" ]]; then
  echo "==> truncating Postgres operational tables"
  docker compose exec -T postgres psql -U "${POSTGRES_USER:-agentshield}" -d "${POSTGRES_DB:-agentshield}" \
    -c "TRUNCATE test_runs, alert_feedback, investigations; DELETE FROM agents;" || true
fi

echo "==> starting stream processor"
docker compose up -d spark-streaming
echo "reset complete"
