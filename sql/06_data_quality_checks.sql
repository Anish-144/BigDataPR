-- =============================================================================
-- 06 - Data-quality checks
-- Structural problems (malformed JSON, missing IDs, unknown types, unparseable
-- timestamps) are quarantined by Spark into dead_letter_events. Semantic problems
-- (duplicates, negative durations, orphan spans, clock skew) are kept and
-- detected here. The integration test asserts these checks find exactly the
-- number of issues the generator injected.
-- =============================================================================

-- @query: dq_scorecard
-- @title: Data-quality scorecard (one row per check)
-- @concept: CTE per check + UNION ALL into a single scorecard
-- @question: How healthy is the curated data overall?
-- @interpretation: issue_rate_pct is issues / rows checked. Non-zero counts are expected when a scenario injects
--   dirty data (dirty_rate > 0); compare them with the generator's dirty_injected summary.
-- @params: days=30
WITH raw AS (
    SELECT * FROM lakehouse.analytics.raw_agent_events
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
),
spans AS (
    SELECT * FROM lakehouse.analytics.agent_spans
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
),
checks AS (
    SELECT 'quarantined_records' AS check_name, count_if(NOT is_valid) AS issues, count(*) AS rows_checked FROM raw
    UNION ALL
    SELECT 'duplicate_event_ids', count(*) - count(DISTINCT event_id), count(*) FROM raw WHERE is_valid
    UNION ALL
    SELECT 'null_trace_ids_in_spans', count_if(trace_id IS NULL OR span_id IS NULL), count(*) FROM spans
    UNION ALL
    SELECT 'negative_span_durations', count_if(duration_ms < 0), count(*) FROM spans
    UNION ALL
    SELECT 'end_before_start', count_if(end_time < start_time), count(*) FROM spans
    UNION ALL
    SELECT 'future_event_times', count_if(contains(dq_flags, 'future_event_time')), count(*) FROM spans
    UNION ALL
    SELECT 'orphan_spans', count(*), (SELECT count(*) FROM spans WHERE parent_span_id IS NOT NULL)
    FROM spans c
    WHERE c.parent_span_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM spans p WHERE p.trace_id = c.trace_id AND p.span_id = c.parent_span_id)
)
SELECT
    check_name,
    issues,
    rows_checked,
    round(100e0 * issues / nullif(rows_checked, 0), 4) AS issue_rate_pct,
    IF(issues = 0, 'PASS', 'REVIEW')                   AS result
FROM checks
ORDER BY issues DESC;

-- @query: dq_null_ids
-- @title: Null identifiers per curated table
-- @concept: Conditional aggregation across UNION ALL of several fact tables
-- @question: Do any curated rows lack the shared keys every module relies on?
-- @interpretation: Spark rejects events missing required context, so these should be zero; a non-zero value would
--   indicate a contract change that bypassed validation.
-- @params: days=30
SELECT 'agent_spans' AS table_name, count(*) AS rows_checked,
       count_if(event_id IS NULL) AS null_event_id, count_if(run_id IS NULL) AS null_run_id,
       count_if(trace_id IS NULL) AS null_trace_id, count_if(agent_id IS NULL) AS null_agent_id
FROM lakehouse.analytics.agent_spans WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
UNION ALL
SELECT 'agent_run_metrics', count(*), count_if(event_id IS NULL), count_if(run_id IS NULL),
       count_if(trace_id IS NULL), count_if(agent_id IS NULL)
FROM lakehouse.analytics.agent_run_metrics WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
UNION ALL
SELECT 'agent_evaluation_results', count(*), count_if(event_id IS NULL), count_if(run_id IS NULL),
       count_if(trace_id IS NULL), count_if(agent_id IS NULL)
FROM lakehouse.analytics.agent_evaluation_results WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
UNION ALL
SELECT 'agent_security_findings', count(*), count_if(event_id IS NULL), count_if(run_id IS NULL),
       count_if(trace_id IS NULL), count_if(agent_id IS NULL)
FROM lakehouse.analytics.agent_security_findings WHERE event_date >= current_date - (:days * INTERVAL '1' DAY);

-- @query: dq_duplicate_events
-- @title: Duplicate event IDs (at-least-once delivery / producer retries)
-- @concept: GROUP BY ... HAVING count(*) > 1
-- @question: Which event IDs were ingested more than once, and on which topics?
-- @interpretation: Duplicates are expected under at-least-once delivery. Analytical queries that must be exact
--   can de-duplicate with ROW_NUMBER() OVER (PARTITION BY event_id ...).
-- @params: days=30
SELECT
    kafka_topic,
    event_type,
    count(*)            AS duplicated_event_ids,
    sum(copies - 1)     AS extra_copies
FROM (
    SELECT event_id, kafka_topic, event_type, count(*) AS copies
    FROM lakehouse.analytics.raw_agent_events
    WHERE is_valid AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY event_id, kafka_topic, event_type
    HAVING count(*) > 1
) d
GROUP BY kafka_topic, event_type
ORDER BY extra_copies DESC;

-- @query: dq_orphan_spans
-- @title: Spans whose parent span is missing
-- @concept: Anti-join (LEFT JOIN ... WHERE right side IS NULL)
-- @question: Which traces contain spans pointing to a parent that never arrived (or was quarantined)?
-- @interpretation: Orphans break the trace waterfall. Causes: corrupted parent IDs, or a parent event that was
--   quarantined as structurally invalid (check dead_letter_events for the same trace).
-- @params: days=30
SELECT
    c.test_run_id,
    count(*)                    AS orphan_spans,
    count(DISTINCT c.trace_id)  AS affected_traces,
    min(c.trace_id)             AS example_trace_id
FROM lakehouse.analytics.agent_spans c
LEFT JOIN lakehouse.analytics.agent_spans p
       ON p.trace_id = c.trace_id AND p.span_id = c.parent_span_id
WHERE c.parent_span_id IS NOT NULL
  AND p.span_id IS NULL
  AND c.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY c.test_run_id
ORDER BY orphan_spans DESC;

-- @query: dq_quarantine_reasons
-- @title: Quarantined (dead-letter) records by reason and day
-- @concept: Aggregation over the dead-letter table
-- @question: Why were records rejected by the stream processor, and is the rejection rate stable?
-- @interpretation: Every rejected record is kept (raw bytes + reason) - nothing is silently dropped.
-- @params: days=30
SELECT
    ingest_date,
    validation_error,
    kafka_topic,
    count(*) AS records
FROM lakehouse.analytics.dead_letter_events
WHERE ingest_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY ingest_date, validation_error, kafka_topic
ORDER BY ingest_date DESC, records DESC;

-- @query: dq_timestamp_checks
-- @title: Timestamp sanity: span ordering, clock skew and run-window consistency
-- @concept: Interval arithmetic, joins to the test-run dimension
-- @question: Are event timestamps plausible (ordered, not in the future, inside their test run's window)?
-- @interpretation: For simulated runs event_time lies in the test run's simulated window; for realtime runs it
--   lies between started_at and ended_at. Events outside indicate producer clock problems.
-- @params: days=30
SELECT
    t.test_run_id,
    t.time_mode,
    count(*)                                                                         AS runs,
    count_if(m.end_time < m.start_time)                                              AS end_before_start,
    count_if(m.event_time > m.ingested_at + INTERVAL '1' DAY)                        AS future_events,
    count_if(t.time_mode = 'simulated' AND (m.start_time < t.sim_window_start - INTERVAL '1' MINUTE
                                         OR m.start_time > t.sim_window_end + INTERVAL '1' MINUTE)) AS outside_sim_window,
    round(avg(to_milliseconds(m.ingested_at - m.event_time)) FILTER (WHERE t.time_mode = 'realtime'), 0)
                                                                                     AS avg_event_to_ingest_ms_realtime
FROM lakehouse.analytics.agent_run_metrics m
JOIN lakehouse.analytics.agent_test_runs t ON t.test_run_id = m.test_run_id
WHERE m.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY t.test_run_id, t.time_mode
ORDER BY runs DESC;

-- @query: dq_run_span_consistency
-- @title: Run summary vs span facts consistency
-- @concept: Join an aggregate of child facts back to the parent fact
-- @question: Does each run's reported span_count match the spans actually stored?
-- @interpretation: Mismatches indicate lost or duplicated span events (e.g. a quarantined span or a duplicate).
-- @params: days=30
WITH span_counts AS (
    SELECT trace_id, count(DISTINCT span_id) AS stored_spans
    FROM lakehouse.analytics.agent_spans
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY trace_id
)
SELECT
    m.test_run_id,
    count(*)                                                         AS runs,
    count_if(coalesce(s.stored_spans, 0) = m.span_count)             AS consistent_runs,
    count_if(coalesce(s.stored_spans, 0) < m.span_count)             AS runs_missing_spans,
    count_if(coalesce(s.stored_spans, 0) > m.span_count)             AS runs_with_extra_spans,
    round(100e0 * count_if(coalesce(s.stored_spans, 0) = m.span_count) / count(*), 3) AS consistency_pct
FROM lakehouse.analytics.agent_run_metrics m
LEFT JOIN span_counts s ON s.trace_id = m.trace_id
WHERE m.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY m.test_run_id
ORDER BY runs DESC;
