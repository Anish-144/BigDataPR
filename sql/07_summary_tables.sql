-- =============================================================================
-- 07 - Pre-aggregated summary tables (materialised views maintained by SQL)
--
-- hourly_agent_summary / daily_agent_summary are rebuilt for the last :days days
-- (DELETE + INSERT ... SELECT, i.e. an idempotent partition overwrite). They
-- store a serialized T-Digest sketch of latency so percentiles can be
-- re-aggregated correctly across hours (you cannot average p95s).
-- Refreshed by: python -m lakehouse.run_sql sql/07_summary_tables.sql
--               (Airflow DAG lakehouse_maintenance, or the API refresh endpoint)
-- Trade-off: summaries are fast to query but only as fresh as the last refresh.
-- =============================================================================

CREATE TABLE IF NOT EXISTS lakehouse.analytics.hourly_agent_summary (
    event_hour              timestamp(6) with time zone,
    event_date              date,
    agent_id                varchar,
    agent_name              varchar,
    agent_version           varchar,
    agent_release_seq       integer,
    model_name              varchar,
    runs                    bigint,
    successes               bigint,
    failed_runs             bigint,
    timeout_runs            bigint,
    sum_latency_ms          double,
    p50_latency_ms          double,
    p95_latency_ms          double,
    p99_latency_ms          double,
    latency_tdigest         varbinary,   -- CAST(tdigest AS varbinary): mergeable percentile sketch
    input_tokens            bigint,
    output_tokens           bigint,
    est_cost_usd            double,      -- ESTIMATE (config/pricing.yaml)
    tool_calls              bigint,
    tool_errors             bigint,
    retries                 bigint,
    policy_denials          bigint,
    refreshed_at            timestamp(6) with time zone
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.daily_agent_summary (
    event_date              date,
    agent_id                varchar,
    agent_name              varchar,
    agent_version           varchar,
    agent_release_seq       integer,
    runs                    bigint,
    successes               bigint,
    success_rate            double,
    p50_latency_ms          double,
    p95_latency_ms          double,
    p99_latency_ms          double,
    avg_tokens              double,
    est_cost_usd            double,
    est_cost_per_success    double,
    security_findings       bigint,
    eval_records            bigint,
    refreshed_at            timestamp(6) with time zone
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

-- refresh step 1: remove the window being rebuilt (partition-aligned delete = metadata-only in Iceberg)
-- @params: days=60
DELETE FROM lakehouse.analytics.hourly_agent_summary
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY);

-- refresh step 2: rebuild hourly rows from the curated fact table
-- @params: days=60
INSERT INTO lakehouse.analytics.hourly_agent_summary
SELECT
    date_trunc('hour', event_time)                     AS event_hour,
    event_date,
    agent_id,
    max(agent_name)                                    AS agent_name,
    agent_version,
    max(agent_release_seq)                             AS agent_release_seq,
    max(model_name)                                    AS model_name,
    count(*)                                           AS runs,
    count_if(task_success)                             AS successes,
    count_if(status = 'failed')                        AS failed_runs,
    count_if(status = 'timeout')                       AS timeout_runs,
    sum(latency_ms)                                    AS sum_latency_ms,
    approx_percentile(latency_ms, 0.50)                AS p50_latency_ms,
    approx_percentile(latency_ms, 0.95)                AS p95_latency_ms,
    approx_percentile(latency_ms, 0.99)                AS p99_latency_ms,
    CAST(tdigest_agg(latency_ms) AS varbinary)         AS latency_tdigest,
    sum(input_tokens)                                  AS input_tokens,
    sum(output_tokens)                                 AS output_tokens,
    sum(estimated_cost_usd)                            AS est_cost_usd,
    sum(tool_calls)                                    AS tool_calls,
    sum(tool_errors + tool_timeouts)                   AS tool_errors,
    sum(retries)                                       AS retries,
    sum(policy_denials)                                AS policy_denials,
    current_timestamp                                  AS refreshed_at
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY date_trunc('hour', event_time), event_date, agent_id, agent_version;

-- @params: days=60
DELETE FROM lakehouse.analytics.daily_agent_summary
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY);

-- daily rows are rolled up from the hourly summary; percentiles come from merged T-Digests
-- @params: days=60
INSERT INTO lakehouse.analytics.daily_agent_summary
WITH daily AS (
    SELECT
        event_date, agent_id, max(agent_name) AS agent_name, agent_version,
        max(agent_release_seq) AS agent_release_seq,
        sum(runs) AS runs, sum(successes) AS successes,
        merge(CAST(latency_tdigest AS tdigest)) AS digest,
        sum(input_tokens + output_tokens) AS tokens,
        sum(est_cost_usd) AS est_cost_usd
    FROM lakehouse.analytics.hourly_agent_summary
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY event_date, agent_id, agent_version
),
findings AS (
    SELECT event_date, agent_id, agent_version, count(*) AS n
    FROM lakehouse.analytics.agent_security_findings
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
evals AS (
    SELECT event_date, agent_id, agent_version, count(*) AS n
    FROM lakehouse.analytics.agent_evaluation_results
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
)
SELECT
    d.event_date, d.agent_id, d.agent_name, d.agent_version, d.agent_release_seq,
    d.runs, d.successes,
    1e0 * d.successes / d.runs                            AS success_rate,
    value_at_quantile(d.digest, 0.50)                     AS p50_latency_ms,
    value_at_quantile(d.digest, 0.95)                     AS p95_latency_ms,
    value_at_quantile(d.digest, 0.99)                     AS p99_latency_ms,
    1e0 * d.tokens / d.runs                               AS avg_tokens,
    d.est_cost_usd,
    d.est_cost_usd / nullif(d.successes, 0)               AS est_cost_per_success,
    coalesce(f.n, 0)                                      AS security_findings,
    coalesce(e.n, 0)                                      AS eval_records,
    current_timestamp                                     AS refreshed_at
FROM daily d
LEFT JOIN findings f ON f.event_date = d.event_date AND f.agent_id = d.agent_id AND f.agent_version = d.agent_version
LEFT JOIN evals e    ON e.event_date = d.event_date AND e.agent_id = d.agent_id AND e.agent_version = d.agent_version;

-- @query: summary_vs_raw_consistency
-- @title: Summary table vs raw facts consistency check
-- @concept: Reconciliation of a materialised aggregate against its source
-- @question: Do the pre-aggregated daily summaries agree with a direct aggregation of the fact table?
-- @interpretation: Counts must match exactly. Percentiles may differ slightly: the summary's are merged T-Digest
--   sketches, the direct ones approx_percentile digests; both are approximations of the exact value.
-- @params: days=60
WITH direct AS (
    SELECT event_date, agent_id, agent_version, count(*) AS runs, count_if(task_success) AS successes,
           approx_percentile(latency_ms, 0.95) AS p95
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
)
SELECT
    d.event_date,
    d.agent_id,
    d.agent_version,
    d.runs                                                    AS runs_direct,
    s.runs                                                    AS runs_summary,
    d.successes = s.successes                                 AS successes_match,
    round(d.p95, 1)                                           AS p95_direct,
    round(s.p95_latency_ms, 1)                                AS p95_from_merged_tdigest,
    round(100e0 * (s.p95_latency_ms - d.p95) / d.p95, 2)      AS p95_diff_pct
FROM direct d
LEFT JOIN lakehouse.analytics.daily_agent_summary s
       ON s.event_date = d.event_date AND s.agent_id = d.agent_id AND s.agent_version = d.agent_version
ORDER BY abs(coalesce(s.runs, 0) - d.runs) DESC, d.event_date DESC
LIMIT 20;

-- @query: daily_trend_from_summary
-- @title: Daily success, p95 latency and estimated cost trend (from the summary table)
-- @concept: Querying a pre-aggregated table; LAG for day-over-day change
-- @question: How do daily success rate, p95 latency and estimated cost evolve per agent version?
-- @interpretation: Reads only a few hundred summary rows instead of millions of facts - the summary-table pattern.
-- @params: days=60
SELECT
    event_date,
    agent_name,
    agent_version,
    runs,
    round(success_rate, 4)                                                                         AS success_rate,
    round(p95_latency_ms, 1)                                                                       AS p95_latency_ms,
    round(est_cost_usd, 4)                                                                         AS est_cost_usd,
    security_findings,
    round(success_rate - lag(success_rate) OVER (PARTITION BY agent_id, agent_version ORDER BY event_date), 4)
                                                                                                   AS success_delta_vs_prev_day
FROM lakehouse.analytics.daily_agent_summary
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY agent_name, agent_version, event_date;
