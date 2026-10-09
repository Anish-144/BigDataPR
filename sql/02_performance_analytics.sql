-- =============================================================================
-- 02 - Performance analytics (Trino SQL over Iceberg/Parquet)
-- Percentiles, throughput, tool performance, error categories, token/cost use,
-- streaming pipeline lag. Run: python -m lakehouse.run_sql sql/02_performance_analytics.sql
-- Parameters (:name) are bound as prepared-statement parameters.
-- =============================================================================

-- @query: latency_percentiles_by_version
-- @title: Latency percentiles by agent version
-- @concept: Percentiles (approx_percentile), aggregation, GROUP BY
-- @question: How do median and tail latencies (p50/p90/p95/p99) and time-to-first-token compare across agent versions?
-- @interpretation: approx_percentile is computed from a quantile digest (approximate; see exact_vs_approx_p95).
--   Tail percentiles (p95/p99) expose fault-driven outliers (timeouts, loops) that averages hide.
--   TTFT is SIMULATED by the mock agents (the time to first streamed token of the final model call).
-- @params: days=30
SELECT
    agent_name,
    agent_version,
    model_name,
    count(*)                                         AS runs,
    round(avg(latency_ms), 1)                        AS avg_ms,
    round(approx_percentile(latency_ms, 0.50), 1)    AS p50_ms,
    round(approx_percentile(latency_ms, 0.90), 1)    AS p90_ms,
    round(approx_percentile(latency_ms, 0.95), 1)    AS p95_ms,
    round(approx_percentile(latency_ms, 0.99), 1)    AS p99_ms,
    round(approx_percentile(ttft_ms, 0.50), 1)       AS p50_ttft_ms,
    round(avg(total_tokens), 1)                      AS avg_tokens
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY agent_name, agent_version, model_name
ORDER BY p95_ms DESC;

-- @query: exact_vs_approx_p95
-- @title: Exact vs approximate p95 latency
-- @concept: Window functions (ROW_NUMBER, COUNT OVER) to compute an exact percentile; CTEs
-- @question: How large is the approximation error of approx_percentile on our data?
-- @interpretation: The exact p95 is the value at rank ceil(0.95 * n) within each version (nearest-rank method).
--   The difference column quantifies the approximation; small relative error justifies approx_percentile for dashboards.
-- @params: days=30
WITH ranked AS (
    SELECT
        agent_name,
        agent_version,
        latency_ms,
        row_number() OVER (PARTITION BY agent_name, agent_version ORDER BY latency_ms) AS rn,
        count(*)     OVER (PARTITION BY agent_name, agent_version)                     AS n
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
),
exact AS (
    SELECT agent_name, agent_version, max(n) AS runs, max(latency_ms) AS exact_p95_ms
    FROM ranked
    WHERE rn <= ceil(0.95 * n)
    GROUP BY agent_name, agent_version
),
approx AS (
    SELECT agent_name, agent_version, approx_percentile(latency_ms, 0.95) AS approx_p95_ms
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY agent_name, agent_version
)
SELECT
    e.agent_name,
    e.agent_version,
    e.runs,
    round(e.exact_p95_ms, 1)                                                AS exact_p95_ms,
    round(a.approx_p95_ms, 1)                                               AS approx_p95_ms,
    round(100e0 * (a.approx_p95_ms - e.exact_p95_ms) / e.exact_p95_ms, 3)  AS approx_error_pct
FROM exact e
JOIN approx a ON a.agent_name = e.agent_name AND a.agent_version = e.agent_version
ORDER BY abs(a.approx_p95_ms - e.exact_p95_ms) DESC;

-- @query: hourly_throughput
-- @title: Hourly event volume and run throughput
-- @concept: Time-window trend analysis (date_trunc), conditional aggregation (count_if)
-- @question: How many events and agent runs does the platform process per (event-time) hour, and how does task success move?
-- @interpretation: Uses event time (simulated for historical scenarios). Volume shape follows the scenario's
--   schedule; dips in success_rate point to incident windows worth drilling into.
-- @params: days=30
SELECT
    date_trunc('hour', r.event_time)                              AS event_hour,
    count(*)                                                      AS events,
    count_if(r.event_type = 'run.metrics')                        AS runs,
    count_if(r.event_type = 'span.completed')                     AS spans,
    round(count(*) / 3600e0, 2)                                   AS avg_events_per_sec,
    -- only run.metrics rows carry a run outcome (the LEFT JOIN yields NULL for every other event type)
    round(avg(IF(m.task_success, 1e0, 0e0)) FILTER (WHERE r.event_type = 'run.metrics'), 4) AS success_rate
FROM lakehouse.analytics.raw_agent_events r
LEFT JOIN lakehouse.analytics.agent_run_metrics m
       ON r.event_type = 'run.metrics' AND m.event_id = r.event_id AND m.event_date = r.event_date
WHERE r.is_valid
  AND r.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY date_trunc('hour', r.event_time)
ORDER BY event_hour;

-- @query: tool_performance
-- @title: Tool-call performance and reliability
-- @concept: Conditional aggregation, percentiles over span facts
-- @question: Which tools are slow or unreliable, and how often are calls retried, timed out or denied by policy?
-- @interpretation: attempt > 1 marks retries. policy_denied calls never executed (blocked by the runtime guard),
--   so they are excluded from latency statistics.
-- @params: days=30
SELECT
    tool_name,
    count(*)                                                             AS calls,
    count_if(attempt > 1)                                                AS retries,
    count_if(status = 'timeout')                                         AS timeouts,
    count_if(error_category = 'tool_error')                              AS tool_errors,
    count_if(error_category = 'invalid_tool_args')                       AS invalid_args,
    count_if(policy_decision = 'deny')                                   AS policy_denied,
    round(100e0 * count_if(status <> 'ok') / count(*), 2)                AS non_ok_pct,
    round(avg(duration_ms) FILTER (WHERE tool_allowed), 1)               AS avg_ms,
    round(approx_percentile(duration_ms, 0.95) FILTER (WHERE tool_allowed), 1) AS p95_ms
FROM lakehouse.analytics.agent_spans
WHERE span_kind = 'tool_call'
  AND event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY tool_name
ORDER BY calls DESC;

-- @query: error_categories
-- @title: Run outcomes and error categories by agent
-- @concept: Conditional aggregation (pivot with count_if), percentages
-- @question: What are the dominant failure modes per agent version?
-- @interpretation: status is the run outcome; task_success additionally requires a correct, schema-valid answer,
--   so a 'completed' run can still be an unsuccessful task.
-- @params: days=30
SELECT
    agent_name,
    agent_version,
    count(*)                                                        AS runs,
    count_if(status = 'completed')                                  AS completed,
    count_if(status = 'failed')                                     AS failed,
    count_if(status = 'timeout')                                    AS timed_out,
    count_if(NOT task_success)                                      AS unsuccessful_tasks,
    count_if(error_category = 'tool_timeout')                       AS err_tool_timeout,
    count_if(error_category = 'tool_error')                         AS err_tool_error,
    count_if(error_category = 'malformed_response')                 AS err_malformed,
    count_if(error_category = 'retrieval_error')                    AS err_retrieval,
    count_if(error_category = 'tool_budget_exceeded')               AS err_loop_budget,
    round(100e0 * count_if(status <> 'completed') / count(*), 2)    AS error_rate_pct
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY agent_name, agent_version
ORDER BY error_rate_pct DESC;

-- @query: token_and_cost_summary
-- @title: Token usage and ESTIMATED cost by model and agent version
-- @concept: Aggregation with explicit provenance of monetary values
-- @question: How many tokens does each agent version consume and what is the estimated cost?
-- @interpretation: estimated_cost_usd comes from config/pricing.yaml (illustrative local prices for mock models, NOT
--   provider pricing). cost_source records the pricing version; runs without pricing are counted separately.
-- @params: days=30
SELECT
    model_name,
    agent_name,
    agent_version,
    count(*)                                         AS runs,
    sum(input_tokens)                                AS input_tokens,
    sum(output_tokens)                               AS output_tokens,
    round(avg(total_tokens), 1)                      AS avg_tokens_per_run,
    round(sum(estimated_cost_usd), 4)                AS est_total_cost_usd,
    round(avg(estimated_cost_usd) * 1000, 4)         AS est_cost_per_1k_runs_usd,
    count_if(estimated_cost_usd IS NULL)             AS runs_without_pricing,
    max(cost_source)                                 AS cost_source
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY model_name, agent_name, agent_version
ORDER BY est_total_cost_usd DESC;

-- @query: streaming_batch_stats
-- @title: Spark micro-batch throughput and end-to-end ingest lag
-- @concept: Operational analytics over pipeline telemetry; percentiles of batch duration
-- @question: How fast does Spark Structured Streaming process Kafka records, and how far behind does it run?
-- @interpretation: Lag = batch commit time - Kafka record timestamp (queueing + trigger interval + processing).
--   rows_per_sec is per micro-batch (input rows / batch duration), measured, single-node local[4] Spark.
-- @params: days=30
SELECT
    query_name,
    count(*)                                                       AS batches,
    sum(input_rows)                                                AS rows_in,
    sum(invalid_rows)                                              AS rows_invalid,
    round(avg(duration_ms), 0)                                     AS avg_batch_ms,
    round(approx_percentile(duration_ms, 0.95), 0)                 AS p95_batch_ms,
    round(sum(input_rows) / (sum(duration_ms) / 1000e0), 1)        AS rows_per_sec_while_busy,
    round(max(input_rows / (duration_ms / 1000e0)), 1)             AS peak_batch_rows_per_sec,
    round(avg(avg_ingest_lag_ms), 0)                               AS avg_ingest_lag_ms,
    round(max(max_ingest_lag_ms), 0)                               AS max_ingest_lag_ms
FROM lakehouse.analytics.pipeline_batch_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
  AND input_rows > 0
GROUP BY query_name;

-- @query: worker_resource_usage
-- @title: Load-generator worker CPU and memory
-- @concept: Aggregation over resource telemetry joined to test runs
-- @question: How much CPU and memory did the local test workers use, and at what event rate?
-- @interpretation: Measured with psutil inside each generator worker process (sampled every 5 s).
-- @params: days=30
SELECT
    w.test_run_id,
    t.test_run_name,
    count(DISTINCT w.worker_id)                AS workers,
    count(*)                                   AS samples,
    round(avg(w.cpu_percent), 1)               AS avg_cpu_pct,
    round(max(w.memory_mb), 1)                 AS peak_memory_mb,
    round(avg(w.events_per_sec), 1)            AS avg_events_per_sec_per_worker
FROM lakehouse.analytics.worker_resource_metrics w
LEFT JOIN lakehouse.analytics.agent_test_runs t ON t.test_run_id = w.test_run_id
WHERE w.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY w.test_run_id, t.test_run_name
ORDER BY samples DESC;
