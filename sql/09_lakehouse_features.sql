-- =============================================================================
-- 09 - Iceberg lakehouse features: snapshots, time travel, schema evolution,
--      rollback (on a scratch table) and maintenance.
-- Run: python -m lakehouse.run_sql sql/09_lakehouse_features.sql
-- =============================================================================

-- @query: snapshot_history
-- @title: Snapshot history of a streaming-written table
-- @concept: Iceberg "$snapshots" metadata table; every Spark micro-batch commit is a snapshot
-- @question: How many commits has the stream made to agent_run_metrics, and what did each add?
-- @interpretation: The summary map holds Iceberg commit stats plus our agentshield.batch_id property, which the
--   stream uses to skip already-committed tables when a micro-batch is replayed after a crash.
SELECT
    committed_at,
    snapshot_id,
    operation,
    element_at(summary, 'added-records')           AS added_records,
    element_at(summary, 'total-records')           AS total_records,
    element_at(summary, 'added-data-files')        AS added_files,
    element_at(summary, 'agentshield.batch_id')    AS stream_batch_id
FROM lakehouse.analytics."agent_run_metrics$snapshots"
ORDER BY committed_at DESC
LIMIT 15;

-- @query: time_travel_row_counts
-- @title: Time travel - current table vs the table as of one minute ago
-- @concept: FOR TIMESTAMP AS OF (Iceberg time travel; requires a constant expression)
-- @question: How many runs did agent_run_metrics hold one minute ago compared with now?
-- @interpretation: Each snapshot is an immutable table version, so historical reports are reproducible. Snapshot-id
--   time travel (FOR VERSION AS OF <id>) and rollback are demonstrated by benchmarks/lakehouse_features_demo.py.
SELECT 'current' AS version, count(*) AS runs FROM lakehouse.analytics.agent_run_metrics
UNION ALL
SELECT 'as of 1 minute ago', count(*)
FROM lakehouse.analytics.agent_run_metrics FOR TIMESTAMP AS OF (current_timestamp - INTERVAL '1' MINUTE);

-- Scratch table for the schema-evolution / rollback demo (never touches production facts).
CREATE TABLE IF NOT EXISTS lakehouse.analytics.demo_evolution
WITH (format = 'PARQUET', format_version = 2)
AS SELECT run_id, agent_id, agent_version, latency_ms, task_success
   FROM lakehouse.analytics.agent_run_metrics
   LIMIT 1000;

-- Schema evolution: add an optional column. Existing data files are NOT rewritten;
-- old rows read the new column as NULL.
ALTER TABLE lakehouse.analytics.demo_evolution ADD COLUMN IF NOT EXISTS routing_strategy varchar;

INSERT INTO lakehouse.analytics.demo_evolution
SELECT run_id, agent_id, agent_version, latency_ms, task_success, 'cost_aware'
FROM lakehouse.analytics.agent_run_metrics
LIMIT 200;

-- @query: schema_evolution_result
-- @title: Schema evolution - old rows read the added column as NULL
-- @concept: ALTER TABLE ADD COLUMN on Iceberg (metadata-only change)
-- @question: After adding routing_strategy, what do old and new rows contain?
-- @interpretation: Iceberg tracks columns by ID, so adding a column is a metadata operation; no file rewrite.
SELECT coalesce(routing_strategy, '<NULL: written before ADD COLUMN>') AS routing_strategy, count(*) AS rows_
FROM lakehouse.analytics.demo_evolution
GROUP BY 1;

-- @query: rollback_candidates
-- @title: Snapshots of the scratch table (rollback targets)
-- @concept: Iceberg snapshot lineage; rollback with CALL system.rollback_to_snapshot
-- @question: Which snapshot would restore the scratch table to before the last INSERT?
-- @interpretation: To roll back (scratch table only):
--   CALL lakehouse.system.rollback_to_snapshot('analytics', 'demo_evolution', <parent snapshot_id>)
--   benchmarks/lakehouse_features_demo.py performs and verifies this rollback.
SELECT committed_at, snapshot_id, parent_id, operation, element_at(summary, 'added-records') AS added_records,
       element_at(summary, 'total-records') AS total_records
FROM lakehouse.analytics."demo_evolution$snapshots"
ORDER BY committed_at;

-- @query: partitions_overview
-- @title: Partition statistics of the span fact table
-- @concept: Iceberg "$partitions" metadata table
-- @question: How are rows and files distributed across event_date partitions?
-- @interpretation: Balanced, date-aligned partitions keep pruning effective; many tiny files per partition signal
--   that compaction is due.
SELECT "partition".event_date AS event_date, record_count, file_count,
       round(total_size / 1048576e0, 2) AS size_mb
FROM lakehouse.analytics."agent_spans$partitions"
ORDER BY event_date;
