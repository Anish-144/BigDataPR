# Runbook: pipeline operations

- Quarantined records: structurally invalid Kafka records (malformed JSON, missing event_id, unknown event type,
  unparseable timestamp) are kept in raw_agent_events and copied to dead_letter_events with a reason.
- Duplicates: delivery is at-least-once. Duplicates are detected by the data-quality SQL and removed in analytical
  queries with ROW_NUMBER() OVER (PARTITION BY event_id ...).
- Lag: ingest lag is measured from the Kafka timestamp to the Iceberg commit. Large bursts queue behind
  maxOffsetsPerTrigger (300,000 records per micro-batch).
- Small files: each micro-batch commit writes new Parquet files; Iceberg compaction (optimize) rewrites them.
- Summary tables are rebuilt by sql/07_summary_tables.sql and are only as fresh as the last refresh.
