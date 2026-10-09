-- =============================================================================
-- 04 - Regression & cohort comparison (baseline vs candidate versions)
-- Versions are ordered by agent_release_seq (semantic release order), never by
-- the version string.
-- =============================================================================

-- @query: version_regression_lag
-- @title: Version-over-version latency change (LAG by release sequence)
-- @concept: CTE + window functions (LAG, RANK) ordered by a numeric release sequence
-- @question: Did a new release of an agent get slower, and how does each version rank on task success?
-- @interpretation: latency_change_pct compares each version with the previous release of the same agent.
--   Ordering by agent_release_seq avoids lexical-version pitfalls (e.g. '1.10.0' < '1.9.0' as strings).
-- @params: days=30
WITH version_metrics AS (
    SELECT
        agent_name,
        agent_version,
        max(agent_release_seq)                         AS release_seq,
        count(*)                                       AS runs,
        avg(latency_ms)                                AS avg_latency_ms,
        approx_percentile(latency_ms, 0.95)            AS p95_latency_ms,
        avg(IF(task_success, 1e0, 0e0))                AS success_rate,
        avg(input_tokens + output_tokens)              AS avg_tokens
    FROM lakehouse.analytics.agent_run_metrics
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY agent_name, agent_version
),
ranked AS (
    SELECT
        *,
        lag(avg_latency_ms) OVER (PARTITION BY agent_name ORDER BY release_seq) AS previous_version_latency,
        lag(agent_version)  OVER (PARTITION BY agent_name ORDER BY release_seq) AS previous_version,
        rank()              OVER (PARTITION BY agent_name ORDER BY success_rate DESC) AS success_rank
    FROM version_metrics
)
SELECT
    agent_name,
    previous_version,
    agent_version,
    runs,
    round(avg_latency_ms, 1)                                                                           AS avg_latency_ms,
    round(previous_version_latency, 1)                                                                 AS previous_version_latency,
    round(100e0 * (avg_latency_ms - previous_version_latency) / nullif(previous_version_latency, 0), 2) AS latency_change_pct,
    round(p95_latency_ms, 1)                                                                           AS p95_latency_ms,
    round(success_rate, 4)                                                                             AS success_rate,
    round(avg_tokens, 1)                                                                               AS avg_tokens,
    success_rank
FROM ranked
ORDER BY latency_change_pct DESC NULLS LAST;

-- @query: cohort_ab_comparison
-- @title: Baseline vs candidate cohort comparison per agent (A/B)
-- @concept: Cohort comparison with conditional aggregation pivot (FILTER) and deltas
-- @question: For each agent, how does the candidate release compare with the baseline on success, p95 latency,
--   tokens, estimated cost per successful task and security findings?
-- @interpretation: Baseline = lowest release_seq, candidate = highest. Positive delta_p95_pct / delta_cost_per_success_pct
--   are regressions; negative delta_success_pp is a quality regression. Restrict :scenario to a clean A/B suite
--   (e.g. 'regression') so differences come from the versions, not from injected faults.
-- @params: days=30, scenario='regression'
WITH bounds AS (
    SELECT agent_id, min(agent_release_seq) AS base_seq, max(agent_release_seq) AS cand_seq
    FROM lakehouse.analytics.agent_run_metrics
    GROUP BY agent_id
),
runs AS (
    SELECT
        m.*,
        CASE WHEN m.agent_release_seq = b.base_seq THEN 'baseline'
             WHEN m.agent_release_seq = b.cand_seq THEN 'candidate' END AS cohort
    FROM lakehouse.analytics.agent_run_metrics m
    JOIN bounds b ON b.agent_id = m.agent_id
    WHERE m.event_date >= current_date - (:days * INTERVAL '1' DAY)
      AND m.scenario_id = :scenario
),
findings AS (
    SELECT run_id, count(*) AS n FROM lakehouse.analytics.agent_security_findings GROUP BY run_id
),
agg AS (
    SELECT
        r.agent_name,
        max(r.agent_version) FILTER (WHERE cohort = 'baseline')                         AS baseline_version,
        max(r.agent_version) FILTER (WHERE cohort = 'candidate')                        AS candidate_version,
        count(*) FILTER (WHERE cohort = 'baseline')                                     AS baseline_runs,
        count(*) FILTER (WHERE cohort = 'candidate')                                    AS candidate_runs,
        avg(IF(task_success, 1e0, 0e0)) FILTER (WHERE cohort = 'baseline')              AS base_success,
        avg(IF(task_success, 1e0, 0e0)) FILTER (WHERE cohort = 'candidate')             AS cand_success,
        approx_percentile(latency_ms, 0.95) FILTER (WHERE cohort = 'baseline')          AS base_p95,
        approx_percentile(latency_ms, 0.95) FILTER (WHERE cohort = 'candidate')         AS cand_p95,
        avg(total_tokens) FILTER (WHERE cohort = 'baseline')                            AS base_tokens,
        avg(total_tokens) FILTER (WHERE cohort = 'candidate')                           AS cand_tokens,
        sum(estimated_cost_usd) FILTER (WHERE cohort = 'baseline')
          / nullif(count_if(task_success AND cohort = 'baseline'), 0)                   AS base_cost_per_success,
        sum(estimated_cost_usd) FILTER (WHERE cohort = 'candidate')
          / nullif(count_if(task_success AND cohort = 'candidate'), 0)                  AS cand_cost_per_success,
        1000e0 * sum(coalesce(f.n, 0)) FILTER (WHERE cohort = 'baseline')
          / nullif(count(*) FILTER (WHERE cohort = 'baseline'), 0)                      AS base_findings_per_1k,
        1000e0 * sum(coalesce(f.n, 0)) FILTER (WHERE cohort = 'candidate')
          / nullif(count(*) FILTER (WHERE cohort = 'candidate'), 0)                     AS cand_findings_per_1k
    FROM runs r
    LEFT JOIN findings f ON f.run_id = r.run_id
    WHERE cohort IS NOT NULL
    GROUP BY r.agent_name
)
SELECT
    agent_name,
    baseline_version,
    candidate_version,
    baseline_runs,
    candidate_runs,
    round(base_success, 4)                                                   AS base_success,
    round(cand_success, 4)                                                   AS cand_success,
    round(100e0 * (cand_success - base_success), 2)                          AS delta_success_pp,
    round(base_p95, 1)                                                       AS base_p95_ms,
    round(cand_p95, 1)                                                       AS cand_p95_ms,
    round(100e0 * (cand_p95 - base_p95) / nullif(base_p95, 0), 2)            AS delta_p95_pct,
    round(100e0 * (cand_tokens - base_tokens) / nullif(base_tokens, 0), 2)   AS delta_tokens_pct,
    round(base_cost_per_success, 6)                                          AS base_est_cost_per_success,
    round(cand_cost_per_success, 6)                                          AS cand_est_cost_per_success,
    round(100e0 * (cand_cost_per_success - base_cost_per_success)
          / nullif(base_cost_per_success, 0), 2)                             AS delta_cost_per_success_pct,
    round(base_findings_per_1k, 2)                                           AS base_findings_per_1k,
    round(cand_findings_per_1k, 2)                                           AS cand_findings_per_1k
FROM agg
ORDER BY agent_name;

-- @query: retrieval_quality_by_version
-- @title: RAG retrieval and grounding quality by version
-- @concept: Long-to-wide pivot of evaluation records with FILTER; joins evaluations to run facts
-- @question: Did a RAG release regress retrieval (Recall@K, MRR) or grounding (citation coverage, groundedness)?
-- @interpretation: Metrics are deterministic and computed against ground-truth relevant documents. MRR is the mean
--   of per-run reciprocal ranks. Retrieval regressions usually precede answer-quality regressions.
-- @params: days=30
SELECT
    m.agent_name,
    e.agent_version,
    count(DISTINCT e.run_id)                                                     AS evaluated_runs,
    round(avg(e.score) FILTER (WHERE e.metric_name = 'recall_at_k'), 4)          AS recall_at_k,
    round(avg(e.score) FILTER (WHERE e.metric_name = 'precision_at_k'), 4)       AS precision_at_k,
    round(avg(e.score) FILTER (WHERE e.metric_name = 'reciprocal_rank'), 4)      AS mrr,
    round(avg(e.score) FILTER (WHERE e.metric_name = 'citation_coverage'), 4)    AS citation_coverage,
    round(avg(e.score) FILTER (WHERE e.metric_name = 'groundedness'), 4)         AS groundedness,
    round(avg(IF(m.task_success, 1e0, 0e0)), 4)                                  AS task_success_rate
FROM lakehouse.analytics.agent_evaluation_results e
JOIN lakehouse.analytics.agent_run_metrics m ON m.run_id = e.run_id AND m.event_date = e.event_date
WHERE e.evaluator_name IN ('retrieval_evaluator', 'citation_checker')
  AND e.evaluator_type = 'deterministic'
  AND e.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY m.agent_name, e.agent_version
ORDER BY m.agent_name, e.agent_version;

-- @query: quality_metrics_by_version
-- @title: Deterministic quality metrics by version
-- @concept: Conditional aggregation over long-format evaluation records
-- @question: How do schema validity, exact-match accuracy, tool correctness and hallucination indicators compare?
-- @interpretation: All metrics here are deterministic (evaluator_type = 'deterministic'); model-judged scores, if
--   enabled, are stored separately and never mixed into these columns.
-- @params: days=30
SELECT
    agent_id,
    agent_version,
    count(DISTINCT run_id)                                                              AS runs,
    round(avg(score) FILTER (WHERE metric_name = 'schema_validity'), 4)                 AS schema_validity,
    round(avg(score) FILTER (WHERE metric_name = 'exact_match'), 4)                     AS exact_match,
    round(avg(score) FILTER (WHERE metric_name = 'token_f1'), 4)                        AS token_f1,
    round(avg(score) FILTER (WHERE metric_name = 'tool_selection_accuracy'), 4)         AS tool_selection_acc,
    round(avg(score) FILTER (WHERE metric_name = 'tool_argument_accuracy'), 4)          AS tool_argument_acc,
    round(avg(score) FILTER (WHERE metric_name = 'hallucination_flag'), 4)              AS hallucination_flag_rate
FROM lakehouse.analytics.agent_evaluation_results
WHERE evaluator_type = 'deterministic'
  AND event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY agent_id, agent_version
ORDER BY agent_id, agent_version;

-- @query: cost_per_successful_task
-- @title: ESTIMATED cost efficiency per successful task
-- @concept: Ratio of aggregates with NULLIF guard (cost per success, not per request)
-- @question: Which agent version delivers successful tasks most cheaply?
-- @interpretation: A cheaper-per-request version can be more expensive per *successful* task if it fails more often.
--   All monetary values are estimates from config/pricing.yaml (local, illustrative, not provider pricing).
-- @params: days=30
SELECT
    agent_name,
    agent_version,
    round(sum(estimated_cost_usd), 4)                                          AS total_estimated_cost_usd,
    sum(CASE WHEN task_success THEN 1 ELSE 0 END)                              AS successful_tasks,
    round(sum(estimated_cost_usd) / count(*), 6)                               AS estimated_cost_per_request,
    round(sum(estimated_cost_usd)
          / nullif(sum(CASE WHEN task_success THEN 1 ELSE 0 END), 0), 6)       AS estimated_cost_per_success,
    round(sum(total_tokens) * 1e0
          / nullif(sum(CASE WHEN task_success THEN 1 ELSE 0 END), 0), 1)       AS tokens_per_success
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY agent_name, agent_version
ORDER BY estimated_cost_per_success ASC NULLS LAST;

-- @query: prompt_model_comparison
-- @title: Prompt-version x model comparison
-- @concept: GROUP BY multiple dimensions joined to the agent registry (dimension table)
-- @question: How do prompt versions and model configurations compare on success, latency and tokens?
-- @interpretation: Joining the registry dimension adds release dates, enabling "what changed" narratives.
-- @params: days=30
SELECT
    m.prompt_version,
    m.model_name,
    r.released_at,
    count(*)                                         AS runs,
    round(avg(IF(m.task_success, 1e0, 0e0)), 4)      AS success_rate,
    round(approx_percentile(m.latency_ms, 0.5), 1)   AS p50_ms,
    round(avg(m.total_tokens), 1)                    AS avg_tokens,
    round(avg(m.retries), 3)                         AS avg_retries
FROM lakehouse.analytics.agent_run_metrics m
JOIN lakehouse.analytics.agent_registry r
  ON r.agent_id = m.agent_id AND r.agent_version = m.agent_version
WHERE m.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY m.prompt_version, m.model_name, r.released_at
ORDER BY r.released_at;
