-- =============================================================================
-- 03 - Window functions, rankings and Top-N
-- =============================================================================

-- @query: rank_p95_within_model
-- @title: Rank agent versions by p95 latency within each model
-- @concept: Window functions (RANK, DENSE_RANK, PERCENT_RANK) over an aggregated CTE
-- @question: Within each model configuration, which agent version has the worst tail latency?
-- @interpretation: Ranking inside a PARTITION BY model_name compares like with like (same model cost/latency
--   profile), isolating the effect of agent logic and prompts.
-- @params: days=30
WITH per_version AS (
    SELECT
        model_name,
        agent_name,
        agent_version,
        count(*)                              AS runs,
        approx_percentile(latency_ms, 0.95)   AS p95_ms,
        avg(estimated_cost_usd)               AS avg_est_cost_usd
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY model_name, agent_name, agent_version
)
SELECT
    model_name,
    agent_name,
    agent_version,
    runs,
    round(p95_ms, 1)                                                                AS p95_ms,
    rank()         OVER (PARTITION BY model_name ORDER BY p95_ms DESC)              AS p95_rank_in_model,
    dense_rank()   OVER (ORDER BY avg_est_cost_usd DESC)                            AS cost_rank_overall,
    round(percent_rank() OVER (ORDER BY p95_ms), 3)                                 AS p95_percentile_rank
FROM per_version
ORDER BY model_name, p95_rank_in_model;

-- @query: top_expensive_agents
-- @title: Top-N most expensive agent versions and share of total (ESTIMATED cost)
-- @concept: Top-N with ORDER BY/LIMIT, share-of-total via SUM() OVER (), running total
-- @question: Which agent versions drive most of the estimated spend?
-- @interpretation: Costs are estimates from the local pricing table. cumulative_share shows Pareto concentration.
-- @params: days=30
WITH cost AS (
    SELECT agent_name, agent_version, model_name, sum(estimated_cost_usd) AS est_cost_usd, count(*) AS runs
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY agent_name, agent_version, model_name
)
SELECT
    agent_name,
    agent_version,
    model_name,
    runs,
    round(est_cost_usd, 4)                                                              AS est_cost_usd,
    round(100e0 * est_cost_usd / sum(est_cost_usd) OVER (), 2)                          AS share_pct,
    round(100e0 * sum(est_cost_usd) OVER (ORDER BY est_cost_usd DESC
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) / sum(est_cost_usd) OVER (), 2) AS cumulative_share_pct
FROM cost
ORDER BY est_cost_usd DESC
LIMIT 5;

-- @query: top_failures_per_agent
-- @title: Top-3 failure reasons per agent (Top-N per group)
-- @concept: ROW_NUMBER() OVER (PARTITION BY ...) for per-group Top-N
-- @question: What are the three most common failure reasons for each agent?
-- @interpretation: Combines run-level error categories with evaluation failures ('wrong_answer' = completed run whose
--   answer did not match the reference).
-- @params: days=30
WITH reasons AS (
    SELECT
        agent_name,
        coalesce(error_category, IF(task_success, NULL, 'wrong_answer')) AS reason,
        count(*) AS n
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
      AND (error_category IS NOT NULL OR NOT task_success)
    GROUP BY 1, 2
),
ranked AS (
    SELECT *, row_number() OVER (PARTITION BY agent_name ORDER BY n DESC) AS rn
    FROM reasons
)
SELECT agent_name, rn AS rank, reason, n
FROM ranked
WHERE rn <= 3
ORDER BY agent_name, rn;

-- @query: rolling_success_rate
-- @title: Hourly success rate with 6-hour moving average and hour-over-hour change
-- @concept: Moving average (AVG OVER ROWS BETWEEN), LAG for period-over-period change
-- @question: Is task success trending down for any agent, beyond normal hourly noise?
-- @interpretation: The moving average smooths noise; large negative delta_vs_prev_hour values flag sudden drops
--   (e.g. the injected dependency-outage incident in the baseline scenario).
-- @params: days=30, agent_id='ops-tool-agent'
WITH hourly AS (
    SELECT
        agent_id,
        agent_version,
        date_trunc('hour', event_time)            AS hour,
        count(*)                                  AS runs,
        avg(IF(task_success, 1e0, 0e0))           AS success_rate
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
      AND agent_id = :agent_id
    GROUP BY 1, 2, 3
)
SELECT
    agent_id,
    agent_version,
    hour,
    runs,
    round(success_rate, 4)                                                                         AS success_rate,
    round(avg(success_rate) OVER (PARTITION BY agent_version ORDER BY hour
          ROWS BETWEEN 5 PRECEDING AND CURRENT ROW), 4)                                            AS moving_avg_6h,
    round(success_rate - lag(success_rate) OVER (PARTITION BY agent_version ORDER BY hour), 4)    AS delta_vs_prev_hour
FROM hourly
ORDER BY agent_version, hour;

-- @query: highest_risk_scenarios
-- @title: Highest-risk scenarios by security findings per 1,000 runs
-- @concept: Multi-table aggregation, NTILE risk buckets, ranking
-- @question: Which test scenarios (and agent versions) carry the most security risk per unit of traffic?
-- @interpretation: Normalising by runs avoids ranking high-volume scenarios as risky just because they are large.
--   critical_findings are weighted separately because they indicate attempted exfiltration / prohibited actions.
-- @params: days=30
WITH runs AS (
    SELECT scenario_id, agent_name, agent_version, count(*) AS runs
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
findings AS (
    SELECT f.scenario_id, m.agent_name, f.agent_version,
           count(*) AS findings, count_if(f.severity = 'critical') AS critical_findings
    FROM lakehouse.analytics.agent_security_findings f
    JOIN (SELECT DISTINCT agent_id, agent_name FROM lakehouse.analytics.agent_registry) m ON m.agent_id = f.agent_id
    WHERE f.event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
)
SELECT
    r.scenario_id,
    r.agent_name,
    r.agent_version,
    r.runs,
    coalesce(f.findings, 0)                                                 AS findings,
    coalesce(f.critical_findings, 0)                                        AS critical_findings,
    round(1000e0 * coalesce(f.findings, 0) / r.runs, 2)                     AS findings_per_1k_runs,
    ntile(4) OVER (ORDER BY 1e0 * coalesce(f.findings, 0) / r.runs DESC)    AS risk_quartile
FROM runs r
LEFT JOIN findings f
       ON f.scenario_id = r.scenario_id AND f.agent_name = r.agent_name AND f.agent_version = r.agent_version
ORDER BY findings_per_1k_runs DESC
LIMIT 15;

-- @query: cumulative_events_per_test_run
-- @title: Cumulative event volume per test run (running totals)
-- @concept: Running totals with SUM() OVER (PARTITION BY ... ORDER BY ...)
-- @question: How did event volume accumulate over each test run's (event-time) timeline?
-- @interpretation: Running totals per test run make ingestion progress and run size directly comparable.
-- @params: days=30
WITH per_hour AS (
    SELECT test_run_id, date_trunc('hour', event_time) AS hour, count(*) AS events
    FROM lakehouse.analytics.raw_agent_events
    WHERE is_valid AND test_run_id IS NOT NULL
      AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2
)
SELECT
    test_run_id,
    hour,
    events,
    sum(events) OVER (PARTITION BY test_run_id ORDER BY hour)   AS cumulative_events
FROM per_hour
ORDER BY test_run_id, hour;
