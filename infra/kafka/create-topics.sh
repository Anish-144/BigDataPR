#!/bin/bash
# Idempotently creates the AgentShield Kafka topics (single broker => RF 1).
set -euo pipefail
BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9092}"
RETENTION_MS="${TOPIC_RETENTION_MS:-604800000}"   # 7 days
KT=/opt/kafka/bin/kafka-topics.sh

create() {
  local topic=$1 partitions=$2
  $KT --bootstrap-server "$BOOTSTRAP" --create --if-not-exists --topic "$topic" \
      --partitions "$partitions" --replication-factor 1 \
      --config retention.ms="$RETENTION_MS" --config compression.type=producer >/dev/null
  echo "topic ready: $topic ($partitions partitions)"
}

create agent-traces 6
create agent-metrics 3
create agent-evaluations 6
create agent-security-events 3
create agent-alerts 3
create agent-events-dlq 1

$KT --bootstrap-server "$BOOTSTRAP" --list
