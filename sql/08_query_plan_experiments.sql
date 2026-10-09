-- =============================================================================
-- 08 - Query plans and table-layout experiments
--
-- benchmarks/sql_benchmark.py runs the experiment queries repeatedly and records
-- measured latency, processed rows/bytes and physical input bytes to
-- benchmarks/results/. Only measured differences are reported - on small local
-- datasets some optimisations show little or no speed-up.
-- =============================================================================

-- @query: plan_partition_pruning
-- @title: EXPLAIN - partition pruning on event_date
-- @concept: EXPLAIN (TYPE DISTRIBUTED); Iceberg partition pruning; predicate pushdown
-- @question: Does a filter on the partition column limit which data files Trino scans?
-- @interpretation: Look for the event_date constraint pushed into the TableScan (connector-level constraint).
--   Iceberg prunes whole partitions (and files by min/max stats) before any Parquet is read.
--   (Literal filter: Trino does not bind prepared-statement parameters inside EXPLAIN (TYPE ...).)
EXPLAIN (TYPE DISTRIBUTED)
SELECT agent_id, count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - INTERVAL '1' DAY
GROUP BY agent_id;

-- @query: analyze_with_partition_filter
-- @title: EXPLAIN ANALYZE - one day of data (partition filter)
-- @concept: EXPLAIN ANALYZE (actual rows/bytes read per operator)
-- @question: How many rows and bytes are physically read when filtering on the partition column?
-- @interpretation: Compare 'Input:' rows/bytes of the ScanFilter operator with analyze_without_partition_filter.
-- @params: days=0
EXPLAIN ANALYZE
SELECT agent_id, count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY agent_id;

-- @query: analyze_without_partition_filter
-- @title: EXPLAIN ANALYZE - full table scan (no partition filter)
-- @concept: EXPLAIN ANALYZE baseline for pruning comparison
-- @question: What does the same aggregation cost without a partition filter?
-- @interpretation: Every partition is read; the difference to the filtered plan is the pruning benefit.
-- @params: days=0
EXPLAIN ANALYZE
SELECT agent_id, count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95
FROM lakehouse.analytics.agent_run_metrics
GROUP BY agent_id;

-- @query: analyze_column_projection
-- @title: EXPLAIN ANALYZE - columnar projection (2 columns of a wide table)
-- @concept: Parquet columnar reads: only referenced columns are fetched
-- @question: How many bytes are read when a query touches 2 of the 22 columns of raw_agent_events?
-- @interpretation: raw_value (full JSON) dominates the table size; queries that do not reference it skip those
--   column chunks entirely. Compare physical input bytes with exp_tier_raw_json, which must read raw_value.
-- @params: days=60
EXPLAIN ANALYZE
SELECT event_type, count(*) AS events
FROM lakehouse.analytics.raw_agent_events
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY event_type;

-- -----------------------------------------------------------------------------
-- Three-tier experiment: the SAME question answered from
--   (1) raw JSON (schema-on-read), (2) curated Iceberg facts, (3) summary table.
-- Question: daily task success rate per agent version.
-- -----------------------------------------------------------------------------

-- @query: exp_tier_raw_json
-- @title: Tier 1 - daily success rate from raw JSON (schema-on-read)
-- @concept: JSON functions over the bronze table; full-column reads of raw_value
-- @question: Daily success rate per agent version, computed directly from raw Kafka payloads.
-- @interpretation: Must read and parse the large raw_value column for every run.metrics event (slowest tier).
-- @params: days=60
SELECT
    event_date,
    agent_id,
    agent_version,
    count(*) AS runs,
    round(avg(IF(json_extract_scalar(raw_value, '$.payload.task_success') = 'true', 1e0, 0e0)), 4) AS success_rate
FROM lakehouse.analytics.raw_agent_events
WHERE is_valid
  AND event_type = 'run.metrics'
  AND event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY event_date, agent_id, agent_version
ORDER BY event_date, agent_id, agent_version;

-- @query: exp_tier_curated
-- @title: Tier 2 - daily success rate from curated Iceberg facts
-- @concept: Typed columnar facts, partition pruning
-- @question: Daily success rate per agent version from agent_run_metrics.
-- @interpretation: Reads two narrow typed columns (task_success, keys) instead of JSON text.
-- @params: days=60
SELECT
    event_date,
    agent_id,
    agent_version,
    count(*) AS runs,
    round(avg(IF(task_success, 1e0, 0e0)), 4) AS success_rate
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY event_date, agent_id, agent_version
ORDER BY event_date, agent_id, agent_version;

-- @query: exp_tier_summary
-- @title: Tier 3 - daily success rate from the pre-aggregated summary table
-- @concept: Materialised aggregate (one row per day x agent version)
-- @question: Daily success rate per agent version from daily_agent_summary.
-- @interpretation: Reads a handful of pre-aggregated rows; freshness depends on the last summary refresh.
-- @params: days=60
SELECT
    event_date,
    agent_id,
    agent_version,
    runs,
    round(success_rate, 4) AS success_rate
FROM lakehouse.analytics.daily_agent_summary
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY event_date, agent_id, agent_version;

-- -----------------------------------------------------------------------------
-- Table-layout experiment: point lookups by trace_id on an unsorted vs a
-- trace_id-sorted copy of agent_spans. Sorting narrows each Parquet file's
-- min/max range for trace_id, so Iceberg/Trino can skip files.
-- (benchmarks/sql_benchmark.py recreates the sorted copy before measuring.)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_spans_sorted_by_trace
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date'], sorted_by = ARRAY['trace_id'])
AS SELECT * FROM lakehouse.analytics.agent_spans;

-- @query: layout_lookup_unsorted
-- @title: Trace lookup on the streaming-written (unsorted) span table
-- @concept: File skipping via Parquet/Iceberg min-max statistics (or lack of it)
-- @question: How many data files and rows must be read to fetch one trace from agent_spans?
-- @interpretation: Streaming micro-batches write files whose trace_id ranges overlap, so little can be skipped.
-- @params: trace_id='00000000000000000000000000000000'
EXPLAIN ANALYZE
SELECT span_id, span_kind, duration_ms
FROM lakehouse.analytics.agent_spans
WHERE trace_id = :trace_id;

-- @query: layout_lookup_sorted
-- @title: Trace lookup on the trace_id-sorted copy
-- @concept: Sorted table layout (sorted_by) enabling file skipping
-- @question: Does sorting by trace_id reduce the data read for the same lookup?
-- @interpretation: Compare input rows / files with layout_lookup_unsorted. The trade-off: sorting costs write time
--   and is a batch (maintenance) operation, not something the streaming writer does per micro-batch.
-- @params: trace_id='00000000000000000000000000000000'
EXPLAIN ANALYZE
SELECT span_id, span_kind, duration_ms
FROM lakehouse.analytics.agent_spans_sorted_by_trace
WHERE trace_id = :trace_id;

-- @query: files_per_partition
-- @title: Iceberg data files per partition (small-files check)
-- @concept: Iceberg metadata tables ("$files") queried with SQL
-- @question: How many data files does each table/partition have, and how big are they?
-- @interpretation: Frequent streaming commits create many small files; compaction (sql/09: optimize) rewrites
--   them into fewer, larger files, which reduces per-file open/plan overhead for queries.
SELECT
    'agent_spans' AS table_name,
    "partition".event_date AS event_date,
    count(*) AS data_files,
    sum(record_count) AS records,
    round(sum(file_size_in_bytes) / 1048576e0, 2) AS size_mb,
    round(avg(file_size_in_bytes) / 1024e0, 1) AS avg_file_kb
FROM lakehouse.analytics."agent_spans$files"
GROUP BY "partition".event_date
UNION ALL
SELECT
    'raw_agent_events',
    "partition".event_date,
    count(*),
    sum(record_count),
    round(sum(file_size_in_bytes) / 1048576e0, 2),
    round(avg(file_size_in_bytes) / 1024e0, 1)
FROM lakehouse.analytics."raw_agent_events$files"
GROUP BY "partition".event_date
ORDER BY table_name, event_date;

-- @query: storage_footprint
-- @title: Lakehouse storage footprint per table (Parquet/ZSTD on MinIO)
-- @concept: Iceberg metadata ($files) aggregation; compression ratio estimate
-- @question: How much object storage does each table use, and how many bytes per row?
-- @interpretation: Sizes are compressed Parquet bytes reported by Iceberg metadata (actual files on MinIO).
SELECT 'raw_agent_events' AS table_name, count(*) AS files, sum(record_count) AS records,
       round(sum(file_size_in_bytes) / 1048576e0, 2) AS size_mb,
       round(1e0 * sum(file_size_in_bytes) / nullif(sum(record_count), 0), 1) AS bytes_per_row
FROM lakehouse.analytics."raw_agent_events$files"
UNION ALL SELECT 'agent_spans', count(*), sum(record_count), round(sum(file_size_in_bytes) / 1048576e0, 2),
       round(1e0 * sum(file_size_in_bytes) / nullif(sum(record_count), 0), 1)
FROM lakehouse.analytics."agent_spans$files"
UNION ALL SELECT 'agent_run_metrics', count(*), sum(record_count), round(sum(file_size_in_bytes) / 1048576e0, 2),
       round(1e0 * sum(file_size_in_bytes) / nullif(sum(record_count), 0), 1)
FROM lakehouse.analytics."agent_run_metrics$files"
UNION ALL SELECT 'agent_evaluation_results', count(*), sum(record_count), round(sum(file_size_in_bytes) / 1048576e0, 2),
       round(1e0 * sum(file_size_in_bytes) / nullif(sum(record_count), 0), 1)
FROM lakehouse.analytics."agent_evaluation_results$files"
UNION ALL SELECT 'agent_security_findings', count(*), sum(record_count), round(sum(file_size_in_bytes) / 1048576e0, 2),
       round(1e0 * sum(file_size_in_bytes) / nullif(sum(record_count), 0), 1)
FROM lakehouse.analytics."agent_security_findings$files"
UNION ALL SELECT 'daily_agent_summary', count(*), sum(record_count), round(sum(file_size_in_bytes) / 1048576e0, 2),
       round(1e0 * sum(file_size_in_bytes) / nullif(sum(record_count), 0), 1)
FROM lakehouse.analytics."daily_agent_summary$files"
ORDER BY size_mb DESC;
