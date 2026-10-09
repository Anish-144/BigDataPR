# SQL showcase

Every query below is in the `sql/` directory, runs on Trino over Iceberg/Parquet, and is also served by the API's read-only query gallery. Sample outputs are **real results** exported from the current dataset with `python -m lakehouse.run_sql "sql/0[2-9]*.sql" --export docs/sql_outputs`; elapsed times are single-node Trino wall times. Parameters (`:days`, ...) are bound as prepared-statement parameters.

Notes for readers: `1e0` literals are DOUBLE on purpose - `1.0` is DECIMAL(2,1) in Trino and `avg()` over it silently rounds rates to one decimal place. `approx_percentile` is approximate (see exact_vs_approx_p95).

## Contents

- `02_performance_analytics.sql`: [latency_percentiles_by_version](#latency-percentiles-by-version), [exact_vs_approx_p95](#exact-vs-approx-p95), [hourly_throughput](#hourly-throughput), [tool_performance](#tool-performance), [error_categories](#error-categories), [token_and_cost_summary](#token-and-cost-summary), [streaming_batch_stats](#streaming-batch-stats), [worker_resource_usage](#worker-resource-usage)
- `03_window_functions_and_rankings.sql`: [rank_p95_within_model](#rank-p95-within-model), [top_expensive_agents](#top-expensive-agents), [top_failures_per_agent](#top-failures-per-agent), [rolling_success_rate](#rolling-success-rate), [highest_risk_scenarios](#highest-risk-scenarios), [cumulative_events_per_test_run](#cumulative-events-per-test-run)
- `04_regression_comparison.sql`: [version_regression_lag](#version-regression-lag), [cohort_ab_comparison](#cohort-ab-comparison), [retrieval_quality_by_version](#retrieval-quality-by-version), [quality_metrics_by_version](#quality-metrics-by-version), [cost_per_successful_task](#cost-per-successful-task), [prompt_model_comparison](#prompt-model-comparison)
- `05_security_correlation.sql`: [findings_by_rule_and_severity](#findings-by-rule-and-severity), [findings_with_trace_evidence](#findings-with-trace-evidence), [anomaly_security_correlation](#anomaly-security-correlation), [window_correlation_perf_errors_security](#window-correlation-perf-errors-security), [exfiltration_sequences](#exfiltration-sequences), [security_detection_vs_ground_truth](#security-detection-vs-ground-truth)
- `06_data_quality_checks.sql`: [dq_scorecard](#dq-scorecard), [dq_null_ids](#dq-null-ids), [dq_duplicate_events](#dq-duplicate-events), [dq_orphan_spans](#dq-orphan-spans), [dq_quarantine_reasons](#dq-quarantine-reasons), [dq_timestamp_checks](#dq-timestamp-checks), [dq_run_span_consistency](#dq-run-span-consistency)
- `07_summary_tables.sql`: [summary_vs_raw_consistency](#summary-vs-raw-consistency), [daily_trend_from_summary](#daily-trend-from-summary)
- `08_query_plan_experiments.sql`: [plan_partition_pruning](#plan-partition-pruning), [analyze_with_partition_filter](#analyze-with-partition-filter), [analyze_without_partition_filter](#analyze-without-partition-filter), [analyze_column_projection](#analyze-column-projection), [exp_tier_raw_json](#exp-tier-raw-json), [exp_tier_curated](#exp-tier-curated), [exp_tier_summary](#exp-tier-summary), [layout_lookup_unsorted](#layout-lookup-unsorted), [layout_lookup_sorted](#layout-lookup-sorted), [files_per_partition](#files-per-partition), [storage_footprint](#storage-footprint)
- `09_lakehouse_features.sql`: [snapshot_history](#snapshot-history), [time_travel_row_counts](#time-travel-row-counts), [schema_evolution_result](#schema-evolution-result), [rollback_candidates](#rollback-candidates), [partitions_overview](#partitions-overview)

## 02_performance_analytics.sql

### latency_percentiles_by_version

**Latency percentiles by agent version**

- **Question:** How do median and tail latencies (p50/p90/p95/p99) and time-to-first-token compare across agent versions?
- **SQL concepts:** Percentiles (approx_percentile), aggregation, GROUP BY
- **Interpretation:** approx_percentile is computed from a quantile digest (approximate; see exact_vs_approx_p95). Tail percentiles (p95/p99) expose fault-driven outliers (timeouts, loops) that averages hide. TTFT is SIMULATED by the mock agents (the time to first streamed token of the final model call).
- **Parameters:** `days=30`

```sql
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
ORDER BY p95_ms DESC
```

Sample output - 8 row(s) shown from export, elapsed 155 ms, processed rows 45980:

| agent_name | agent_version | model_name | runs | avg_ms | p50_ms | p90_ms | p95_ms | p99_ms | p50_ttft_ms | avg_tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| Planner Agent | 2.0.0 | mock-large | 5688 | 4369.5 | 4100.9 | 5867.5 | 6548.9 | 11661.1 | 3054.7 | 3527.6 |
| Planner Agent | 1.0.0 | mock-large | 5724 | 3831.0 | 3496.6 | 5092.1 | 5804.7 | 10552.8 | 2379.5 | 2594.8 |
| RAG Helpdesk | 2.0.0 | mock-medium | 5827 | 1704.2 | 1477.5 | 2217.1 | 2623.3 | 4659.2 | 728.4 | 1937.6 |
| Ops Tool Agent | 1.1.0 | mock-small | 5654 | 1592.7 | 1383.3 | 1910.8 | 2197.5 | 4545.2 | 895.5 | 1021.8 |
| RAG Helpdesk | 2.1.0 | mock-medium | 5788 | 1463.1 | 1283.7 | 1872.1 | 2166.8 | 3639.1 | 631.1 | 1432.8 |
| Ops Tool Agent | 1.0.0 | mock-small | 5793 | 1407.3 | 1211.0 | 1637.0 | 1851.7 | 4230.7 | 787.7 | 792.7 |
| QA Assistant | 1.1.0 | mock-medium | 5752 | 979.2 | 914.2 | 1388.3 | 1590.6 | 2161.9 | 181.7 | 621.2 |
| QA Assistant | 1.0.0 | mock-small | 5754 | 704.5 | 644.0 | 1031.4 | 1207.9 | 1692.3 | 142.2 | 509.4 |

### exact_vs_approx_p95

**Exact vs approximate p95 latency**

- **Question:** How large is the approximation error of approx_percentile on our data?
- **SQL concepts:** Window functions (ROW_NUMBER, COUNT OVER) to compute an exact percentile; CTEs
- **Interpretation:** The exact p95 is the value at rank ceil(0.95 * n) within each version (nearest-rank method). The difference column quantifies the approximation; small relative error justifies approx_percentile for dashboards.
- **Parameters:** `days=30`

```sql
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
ORDER BY abs(a.approx_p95_ms - e.exact_p95_ms) DESC
```

Sample output - 8 row(s) shown from export, elapsed 164 ms, processed rows 91960:

| agent_name | agent_version | runs | exact_p95_ms | approx_p95_ms | approx_error_pct |
|---|---|---|---|---|---|
| Planner Agent | 2.0.0 | 5688 | 6537.8 | 6567.5 | 0.454 |
| Planner Agent | 1.0.0 | 5724 | 5835.9 | 5808.9 | -0.463 |
| RAG Helpdesk | 2.1.0 | 5788 | 2164.9 | 2181.4 | 0.766 |
| QA Assistant | 1.1.0 | 5752 | 1582.1 | 1594.8 | 0.802 |
| Ops Tool Agent | 1.1.0 | 5654 | 2182.7 | 2191.8 | 0.415 |
| Ops Tool Agent | 1.0.0 | 5793 | 1854.2 | 1848.0 | -0.337 |
| RAG Helpdesk | 2.0.0 | 5827 | 2615.3 | 2619.3 | 0.152 |
| QA Assistant | 1.0.0 | 5754 | 1206.3 | 1206.9 | 0.048 |

### hourly_throughput

**Hourly event volume and run throughput**

- **Question:** How many events and agent runs does the platform process per (event-time) hour, and how does task success move?
- **SQL concepts:** Time-window trend analysis (date_trunc), conditional aggregation (count_if)
- **Interpretation:** Uses event time (simulated for historical scenarios). Volume shape follows the scenario's schedule; dips in success_rate point to incident windows worth drilling into.
- **Parameters:** `days=30`

```sql
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
ORDER BY event_hour
```

Sample output - 73 row(s) shown from export, elapsed 249 ms, processed rows 768334:

| event_hour | events | runs | spans | avg_events_per_sec | success_rate |
|---|---|---|---|---|---|
| 2026-10-06T15:00:00+00:00 | 2432 | 170 | 1087 | 0.68 | 0.0559 |
| 2026-10-06T16:00:00+00:00 | 4144 | 278 | 1860 | 1.15 | 0.0579 |
| 2026-10-06T17:00:00+00:00 | 4015 | 276 | 1795 | 1.12 | 0.0573 |
| 2026-10-06T18:00:00+00:00 | 4040 | 280 | 1806 | 1.12 | 0.0564 |
| 2026-10-06T19:00:00+00:00 | 4079 | 279 | 1833 | 1.13 | 0.0534 |
| 2026-10-06T20:00:00+00:00 | 3984 | 277 | 1776 | 1.11 | 0.0555 |
| 2026-10-06T21:00:00+00:00 | 4083 | 280 | 1823 | 1.13 | 0.0561 |
| 2026-10-06T22:00:00+00:00 | 4080 | 278 | 1829 | 1.13 | 0.0537 |
| 2026-10-06T23:00:00+00:00 | 4000 | 277 | 1798 | 1.11 | 0.0598 |
| 2026-10-07T00:00:00+00:00 | 4024 | 278 | 1794 | 1.12 | 0.0574 |
| 2026-10-07T01:00:00+00:00 | 3992 | 278 | 1803 | 1.11 | 0.0601 |
| 2026-10-07T02:00:00+00:00 | 4125 | 278 | 1869 | 1.15 | 0.0553 |

_61 more rows not shown (full result in docs/sql_outputs)._

### tool_performance

**Tool-call performance and reliability**

- **Question:** Which tools are slow or unreliable, and how often are calls retried, timed out or denied by policy?
- **SQL concepts:** Conditional aggregation, percentiles over span facts
- **Interpretation:** attempt > 1 marks retries. policy_denied calls never executed (blocked by the runtime guard), so they are excluded from latency statistics.
- **Parameters:** `days=30`

```sql
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
ORDER BY calls DESC
```

Sample output - 13 row(s) shown from export, elapsed 132 ms, processed rows 302580:

| tool_name | calls | retries | timeouts | tool_errors | invalid_args | policy_denied | non_ok_pct | avg_ms | p95_ms |
|---|---|---|---|---|---|---|---|---|---|
| document_lookup | 19764 | 394 | 153 | 270 | 265 | 1 | 3.49 | 209.9 | 260.3 |
| search_kb | 10600 | 496 | 86 | 429 | 0 | 13 | 4.98 | 233.9 | 283.2 |
| get_order_status | 8430 | 432 | 111 | 351 | 265 | 46 | 9.17 | 277.1 | 294.5 |
| calculator | 8398 | 928 | 74 | 1145 | 0 | 38 | 14.97 | 234.4 | 282.9 |
| create_ticket | 7736 | 308 | 39 | 278 | 265 | 26 | 7.86 | 200.3 | 279.7 |
| delegate_subtask | 4470 | 193 | 68 | 139 | 0 | 0 | 4.63 | 299.2 | 299.4 |
| export_data | 152 | 0 | 0 | 0 | 0 | 152 | 100.0 | NULL | NULL |
| http_post | 140 | 0 | 0 | 0 | 0 | 140 | 100.0 | NULL | NULL |
| send_external_email | 130 | 0 | 0 | 0 | 0 | 130 | 100.0 | NULL | NULL |
| modify_permissions | 104 | 0 | 0 | 0 | 0 | 104 | 100.0 | NULL | NULL |
| read_resource | 104 | 0 | 0 | 0 | 0 | 104 | 100.0 | NULL | NULL |
| execute_shell | 78 | 0 | 0 | 0 | 0 | 78 | 100.0 | NULL | NULL |

_1 more rows not shown (full result in docs/sql_outputs)._

### error_categories

**Run outcomes and error categories by agent**

- **Question:** What are the dominant failure modes per agent version?
- **SQL concepts:** Conditional aggregation (pivot with count_if), percentages
- **Interpretation:** status is the run outcome; task_success additionally requires a correct, schema-valid answer, so a 'completed' run can still be an unsuccessful task.
- **Parameters:** `days=30`

```sql
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
ORDER BY error_rate_pct DESC
```

Sample output - 8 row(s) shown from export, elapsed 91 ms, processed rows 45980:

| agent_name | agent_version | runs | completed | failed | timed_out | unsuccessful_tasks | err_tool_timeout | err_tool_error | err_malformed | err_retrieval | err_loop_budget | error_rate_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ops Tool Agent | 1.1.0 | 5654 | 5392 | 241 | 21 | 807 | 21 | 81 | 87 | 0 | 31 | 4.63 |
| Planner Agent | 1.0.0 | 5724 | 5475 | 233 | 16 | 2138 | 16 | 82 | 57 | 1 | 0 | 4.35 |
| Ops Tool Agent | 1.0.0 | 5793 | 5578 | 202 | 13 | 574 | 13 | 64 | 65 | 0 | 35 | 3.71 |
| Planner Agent | 2.0.0 | 5688 | 5501 | 181 | 6 | 1486 | 6 | 57 | 55 | 1 | 0 | 3.29 |
| RAG Helpdesk | 2.1.0 | 5788 | 5700 | 88 | 0 | 1159 | 0 | 0 | 55 | 33 | 0 | 1.52 |
| RAG Helpdesk | 2.0.0 | 5827 | 5765 | 62 | 0 | 720 | 0 | 0 | 46 | 16 | 0 | 1.06 |
| QA Assistant | 1.0.0 | 5754 | 5693 | 61 | 0 | 1020 | 0 | 0 | 61 | 0 | 0 | 1.06 |
| QA Assistant | 1.1.0 | 5752 | 5714 | 38 | 0 | 480 | 0 | 0 | 38 | 0 | 0 | 0.66 |

### token_and_cost_summary

**Token usage and ESTIMATED cost by model and agent version**

- **Question:** How many tokens does each agent version consume and what is the estimated cost?
- **SQL concepts:** Aggregation with explicit provenance of monetary values
- **Interpretation:** estimated_cost_usd comes from config/pricing.yaml (illustrative local prices for mock models, NOT provider pricing). cost_source records the pricing version; runs without pricing are counted separately.
- **Parameters:** `days=30`

```sql
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
ORDER BY est_total_cost_usd DESC
```

Sample output - 8 row(s) shown from export, elapsed 78 ms, processed rows 45980:

| model_name | agent_name | agent_version | runs | input_tokens | output_tokens | avg_tokens_per_run | est_total_cost_usd | est_cost_per_1k_runs_usd | runs_without_pricing | cost_source |
|---|---|---|---|---|---|---|---|---|---|---|
| mock-large | Planner Agent | 2.0.0 | 5688 | 16819816 | 3245077 | 3527.6 | 74.5003 | 13.0978 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-large | Planner Agent | 1.0.0 | 5724 | 12254175 | 2598538 | 2594.8 | 56.6208 | 9.8918 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-medium | RAG Helpdesk | 2.0.0 | 5827 | 9851378 | 1438814 | 1937.6 | 12.4853 | 2.1427 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-medium | RAG Helpdesk | 2.1.0 | 5788 | 6971476 | 1321385 | 1432.8 | 9.8056 | 1.6941 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-medium | QA Assistant | 1.1.0 | 5752 | 2718193 | 854738 | 621.2 | 4.9097 | 0.8536 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-small | Ops Tool Agent | 1.1.0 | 5654 | 4608834 | 1168286 | 1021.8 | 1.3923 | 0.2462 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-small | Ops Tool Agent | 1.0.0 | 5793 | 3728161 | 864143 | 792.7 | 1.0777 | 0.186 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-small | QA Assistant | 1.0.0 | 5754 | 2258435 | 672608 | 509.4 | 0.7423 | 0.129 | 0 | local_pricing_config:local-demo-2026.10 |

### streaming_batch_stats

**Spark micro-batch throughput and end-to-end ingest lag**

- **Question:** How fast does Spark Structured Streaming process Kafka records, and how far behind does it run?
- **SQL concepts:** Operational analytics over pipeline telemetry; percentiles of batch duration
- **Interpretation:** Lag = batch commit time - Kafka record timestamp (queueing + trigger interval + processing). rows_per_sec is per micro-batch (input rows / batch duration), measured, single-node local[4] Spark.
- **Parameters:** `days=30`

```sql
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
GROUP BY query_name
```

Sample output - 1 row(s) shown from export, elapsed 97 ms, processed rows 2:

| query_name | batches | rows_in | rows_invalid | avg_batch_ms | p95_batch_ms | rows_per_sec_while_busy | peak_batch_rows_per_sec | avg_ingest_lag_ms | max_ingest_lag_ms |
|---|---|---|---|---|---|---|---|---|---|
| lakehouse_fanout | 2 | 592942 | 446 | 19736.0 | 20390.0 | 15022.2 | 15721.5 | 29876.0 | 40872.0 |

### worker_resource_usage

**Load-generator worker CPU and memory**

- **Question:** How much CPU and memory did the local test workers use, and at what event rate?
- **SQL concepts:** Aggregation over resource telemetry joined to test runs
- **Interpretation:** Measured with psutil inside each generator worker process (sampled every 5 s).
- **Parameters:** `days=30`

```sql
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
ORDER BY samples DESC
```

Sample output - 0 row(s) shown from export, elapsed 130 ms, processed rows 0:

| test_run_id | test_run_name | workers | samples | avg_cpu_pct | peak_memory_mb | avg_events_per_sec_per_worker |
|---|---|---|---|---|---|---|


## 03_window_functions_and_rankings.sql

### rank_p95_within_model

**Rank agent versions by p95 latency within each model**

- **Question:** Within each model configuration, which agent version has the worst tail latency?
- **SQL concepts:** Window functions (RANK, DENSE_RANK, PERCENT_RANK) over an aggregated CTE
- **Interpretation:** Ranking inside a PARTITION BY model_name compares like with like (same model cost/latency profile), isolating the effect of agent logic and prompts.
- **Parameters:** `days=30`

```sql
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
ORDER BY model_name, p95_rank_in_model
```

Sample output - 8 row(s) shown from export, elapsed 114 ms, processed rows 45980:

| model_name | agent_name | agent_version | runs | p95_ms | p95_rank_in_model | cost_rank_overall | p95_percentile_rank |
|---|---|---|---|---|---|---|---|
| mock-large | Planner Agent | 2.0.0 | 5688 | 6549.7 | 1 | 1 | 1.0 |
| mock-large | Planner Agent | 1.0.0 | 5724 | 5802.6 | 2 | 2 | 0.857 |
| mock-medium | RAG Helpdesk | 2.0.0 | 5827 | 2625.1 | 1 | 3 | 0.714 |
| mock-medium | RAG Helpdesk | 2.1.0 | 5788 | 2173.9 | 2 | 4 | 0.429 |
| mock-medium | QA Assistant | 1.1.0 | 5752 | 1593.9 | 3 | 5 | 0.143 |
| mock-small | Ops Tool Agent | 1.1.0 | 5654 | 2174.8 | 1 | 6 | 0.571 |
| mock-small | Ops Tool Agent | 1.0.0 | 5793 | 1854.0 | 2 | 7 | 0.286 |
| mock-small | QA Assistant | 1.0.0 | 5754 | 1203.3 | 3 | 8 | 0.0 |

### top_expensive_agents

**Top-N most expensive agent versions and share of total (ESTIMATED cost)**

- **Question:** Which agent versions drive most of the estimated spend?
- **SQL concepts:** Top-N with ORDER BY/LIMIT, share-of-total via SUM() OVER (), running total
- **Interpretation:** Costs are estimates from the local pricing table. cumulative_share shows Pareto concentration.
- **Parameters:** `days=30`

```sql
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
LIMIT 5
```

Sample output - 5 row(s) shown from export, elapsed 107 ms, processed rows 45980:

| agent_name | agent_version | model_name | runs | est_cost_usd | share_pct | cumulative_share_pct |
|---|---|---|---|---|---|---|
| Planner Agent | 2.0.0 | mock-large | 5688 | 74.5003 | 46.12 | 46.12 |
| Planner Agent | 1.0.0 | mock-large | 5724 | 56.6208 | 35.05 | 81.17 |
| RAG Helpdesk | 2.0.0 | mock-medium | 5827 | 12.4853 | 7.73 | 88.9 |
| RAG Helpdesk | 2.1.0 | mock-medium | 5788 | 9.8056 | 6.07 | 94.97 |
| QA Assistant | 1.1.0 | mock-medium | 5752 | 4.9097 | 3.04 | 98.01 |

### top_failures_per_agent

**Top-3 failure reasons per agent (Top-N per group)**

- **Question:** What are the three most common failure reasons for each agent?
- **SQL concepts:** ROW_NUMBER() OVER (PARTITION BY ...) for per-group Top-N
- **Interpretation:** Combines run-level error categories with evaluation failures ('wrong_answer' = completed run whose answer did not match the reference).
- **Parameters:** `days=30`

```sql
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
ORDER BY agent_name, rn
```

Sample output - 11 row(s) shown from export, elapsed 97 ms, processed rows 45980:

| agent_name | rank | reason | n |
|---|---|---|---|
| Ops Tool Agent | 1 | wrong_answer | 904 |
| Ops Tool Agent | 2 | malformed_response | 152 |
| Ops Tool Agent | 3 | tool_error | 145 |
| Planner Agent | 1 | wrong_answer | 3188 |
| Planner Agent | 2 | invalid_tool_args | 161 |
| Planner Agent | 3 | tool_error | 139 |
| QA Assistant | 1 | wrong_answer | 1401 |
| QA Assistant | 2 | malformed_response | 99 |
| RAG Helpdesk | 1 | wrong_answer | 1729 |
| RAG Helpdesk | 2 | malformed_response | 101 |
| RAG Helpdesk | 3 | retrieval_error | 49 |

### rolling_success_rate

**Hourly success rate with 6-hour moving average and hour-over-hour change**

- **Question:** Is task success trending down for any agent, beyond normal hourly noise?
- **SQL concepts:** Moving average (AVG OVER ROWS BETWEEN), LAG for period-over-period change
- **Interpretation:** The moving average smooths noise; large negative delta_vs_prev_hour values flag sudden drops (e.g. the injected dependency-outage incident in the baseline scenario).
- **Parameters:** `days=30, agent_id='ops-tool-agent'`

```sql
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
ORDER BY agent_version, hour
```

Sample output - 146 row(s) shown from export, elapsed 148 ms, processed rows 45980:

| agent_id | agent_version | hour | runs | success_rate | moving_avg_6h | delta_vs_prev_hour |
|---|---|---|---|---|---|---|
| ops-tool-agent | 1.0.0 | 2026-10-06T15:00:00+00:00 | 23 | 0.7826 | 0.7826 | NULL |
| ops-tool-agent | 1.0.0 | 2026-10-06T16:00:00+00:00 | 41 | 0.9268 | 0.8547 | 0.1442 |
| ops-tool-agent | 1.0.0 | 2026-10-06T17:00:00+00:00 | 32 | 0.9063 | 0.8719 | -0.0206 |
| ops-tool-agent | 1.0.0 | 2026-10-06T18:00:00+00:00 | 35 | 0.9143 | 0.8825 | 0.008 |
| ops-tool-agent | 1.0.0 | 2026-10-06T19:00:00+00:00 | 35 | 0.8857 | 0.8831 | -0.0286 |
| ops-tool-agent | 1.0.0 | 2026-10-06T20:00:00+00:00 | 32 | 0.875 | 0.8818 | -0.0107 |
| ops-tool-agent | 1.0.0 | 2026-10-06T21:00:00+00:00 | 35 | 0.9143 | 0.9037 | 0.0393 |
| ops-tool-agent | 1.0.0 | 2026-10-06T22:00:00+00:00 | 42 | 0.9524 | 0.908 | 0.0381 |
| ops-tool-agent | 1.0.0 | 2026-10-06T23:00:00+00:00 | 41 | 0.9268 | 0.9114 | -0.0256 |
| ops-tool-agent | 1.0.0 | 2026-10-07T00:00:00+00:00 | 36 | 0.8333 | 0.8979 | -0.0935 |
| ops-tool-agent | 1.0.0 | 2026-10-07T01:00:00+00:00 | 33 | 0.9091 | 0.9018 | 0.0758 |
| ops-tool-agent | 1.0.0 | 2026-10-07T02:00:00+00:00 | 39 | 0.9231 | 0.9098 | 0.014 |

_134 more rows not shown (full result in docs/sql_outputs)._

### highest_risk_scenarios

**Highest-risk scenarios by security findings per 1,000 runs**

- **Question:** Which test scenarios (and agent versions) carry the most security risk per unit of traffic?
- **SQL concepts:** Multi-table aggregation, NTILE risk buckets, ranking
- **Interpretation:** Normalising by runs avoids ranking high-volume scenarios as risky just because they are large. critical_findings are weighted separately because they indicate attempted exfiltration / prohibited actions.
- **Parameters:** `days=30`

```sql
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
LIMIT 15
```

Sample output - 15 row(s) shown from export, elapsed 201 ms, processed rows 48666:

| scenario_id | agent_name | agent_version | runs | findings | critical_findings | findings_per_1k_runs | risk_quartile |
|---|---|---|---|---|---|---|---|
| security_suite | RAG Helpdesk | 2.0.0 | 771 | 307 | 102 | 398.18 | 1 |
| security_suite | RAG Helpdesk | 2.1.0 | 715 | 265 | 106 | 370.63 | 1 |
| security_suite | Planner Agent | 1.0.0 | 726 | 246 | 126 | 338.84 | 1 |
| security_suite | Ops Tool Agent | 1.1.0 | 744 | 197 | 109 | 264.78 | 1 |
| security_suite | Planner Agent | 2.0.0 | 721 | 186 | 100 | 257.98 | 1 |
| security_suite | Ops Tool Agent | 1.0.0 | 775 | 199 | 112 | 256.77 | 1 |
| security_suite | QA Assistant | 1.1.0 | 776 | 131 | 79 | 168.81 | 1 |
| security_suite | QA Assistant | 1.0.0 | 772 | 122 | 86 | 158.03 | 1 |
| baseline | RAG Helpdesk | 2.0.0 | 2490 | 209 | 24 | 83.94 | 2 |
| regression | RAG Helpdesk | 2.0.0 | 1023 | 72 | 0 | 70.38 | 2 |
| baseline | RAG Helpdesk | 2.1.0 | 2545 | 174 | 26 | 68.37 | 2 |
| fault_injection | RAG Helpdesk | 2.0.0 | 1543 | 91 | 0 | 58.98 | 2 |

_3 more rows not shown (full result in docs/sql_outputs)._

### cumulative_events_per_test_run

**Cumulative event volume per test run (running totals)**

- **Question:** How did event volume accumulate over each test run's (event-time) timeline?
- **SQL concepts:** Running totals with SUM() OVER (PARTITION BY ... ORDER BY ...)
- **Interpretation:** Running totals per test run make ingestion progress and run size directly comparable.
- **Parameters:** `days=30`

```sql
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
ORDER BY test_run_id, hour
```

Sample output - 124 row(s) shown from export, elapsed 135 ms, processed rows 676374:

| test_run_id | hour | events | cumulative_events |
|---|---|---|---|
| TR-20261009-12eb56 | 2026-10-08T15:00:00+00:00 | 4377 | 4377 |
| TR-20261009-12eb56 | 2026-10-08T16:00:00+00:00 | 7531 | 11908 |
| TR-20261009-12eb56 | 2026-10-08T17:00:00+00:00 | 7416 | 19324 |
| TR-20261009-12eb56 | 2026-10-08T18:00:00+00:00 | 7234 | 26558 |
| TR-20261009-12eb56 | 2026-10-08T19:00:00+00:00 | 7175 | 33733 |
| TR-20261009-12eb56 | 2026-10-08T20:00:00+00:00 | 7315 | 41048 |
| TR-20261009-12eb56 | 2026-10-08T21:00:00+00:00 | 7407 | 48455 |
| TR-20261009-12eb56 | 2026-10-08T22:00:00+00:00 | 7209 | 55664 |
| TR-20261009-12eb56 | 2026-10-08T23:00:00+00:00 | 7356 | 63020 |
| TR-20261009-12eb56 | 2026-10-09T00:00:00+00:00 | 7547 | 70567 |
| TR-20261009-12eb56 | 2026-10-09T01:00:00+00:00 | 7399 | 77966 |
| TR-20261009-12eb56 | 2026-10-09T02:00:00+00:00 | 7560 | 85526 |

_112 more rows not shown (full result in docs/sql_outputs)._


## 04_regression_comparison.sql

### version_regression_lag

**Version-over-version latency change (LAG by release sequence)**

- **Question:** Did a new release of an agent get slower, and how does each version rank on task success?
- **SQL concepts:** CTE + window functions (LAG, RANK) ordered by a numeric release sequence
- **Interpretation:** latency_change_pct compares each version with the previous release of the same agent. Ordering by agent_release_seq avoids lexical-version pitfalls (e.g. '1.10.0' < '1.9.0' as strings).
- **Parameters:** `days=30`

```sql
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
ORDER BY latency_change_pct DESC NULLS LAST
```

Sample output - 8 row(s) shown from export, elapsed 106 ms, processed rows 45980:

| agent_name | previous_version | agent_version | runs | avg_latency_ms | previous_version_latency | latency_change_pct | p95_latency_ms | success_rate | avg_tokens | success_rank |
|---|---|---|---|---|---|---|---|---|---|---|
| QA Assistant | 1.0.0 | 1.1.0 | 5752 | 979.2 | 704.5 | 39.0 | 1590.6 | 0.9166 | 621.2 | 1 |
| Planner Agent | 1.0.0 | 2.0.0 | 5688 | 4369.5 | 3831.0 | 14.06 | 6582.2 | 0.7387 | 3527.6 | 1 |
| Ops Tool Agent | 1.0.0 | 1.1.0 | 5654 | 1592.7 | 1407.3 | 13.17 | 2188.1 | 0.8573 | 1021.8 | 2 |
| RAG Helpdesk | 2.0.0 | 2.1.0 | 5788 | 1463.1 | 1704.2 | -14.15 | 2170.9 | 0.7998 | 1432.8 | 2 |
| Ops Tool Agent | NULL | 1.0.0 | 5793 | 1407.3 | NULL | NULL | 1844.7 | 0.9009 | 792.7 | 1 |
| RAG Helpdesk | NULL | 2.0.0 | 5827 | 1704.2 | NULL | NULL | 2619.4 | 0.8764 | 1937.6 | 1 |
| QA Assistant | NULL | 1.0.0 | 5754 | 704.5 | NULL | NULL | 1204.9 | 0.8227 | 509.4 | 2 |
| Planner Agent | NULL | 1.0.0 | 5724 | 3831.0 | NULL | NULL | 5797.8 | 0.6265 | 2594.8 | 2 |

### cohort_ab_comparison

**Baseline vs candidate cohort comparison per agent (A/B)**

- **Question:** For each agent, how does the candidate release compare with the baseline on success, p95 latency, tokens, estimated cost per successful task and security findings?
- **SQL concepts:** Cohort comparison with conditional aggregation pivot (FILTER) and deltas
- **Interpretation:** Baseline = lowest release_seq, candidate = highest. Positive delta_p95_pct / delta_cost_per_success_pct are regressions; negative delta_success_pp is a quality regression. Restrict :scenario to a clean A/B suite (e.g. 'regression') so differences come from the versions, not from injected faults.
- **Parameters:** `days=30, scenario='regression'`

```sql
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
ORDER BY agent_name
```

Sample output - 4 row(s) shown from export, elapsed 358 ms, processed rows 66590:

| agent_name | baseline_version | candidate_version | baseline_runs | candidate_runs | base_success | cand_success | delta_success_pp | base_p95_ms | cand_p95_ms | delta_p95_pct | delta_tokens_pct | base_est_cost_per_success | cand_est_cost_per_success | delta_cost_per_success_pct | base_findings_per_1k | cand_findings_per_1k |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ops Tool Agent | 1.0.0 | 1.1.0 | 988 | 936 | 0.9119 | 0.8654 | -4.66 | 1735.7 | 1985.1 | 14.37 | 28.7 | 0.0002 | 0.0003 | 38.98 | 0.0 | 0.0 |
| Planner Agent | 1.0.0 | 2.0.0 | 1042 | 1013 | 0.6296 | 0.7345 | 10.49 | 5330.3 | 6065.8 | 13.8 | 36.47 | 0.0149 | 0.0171 | 14.23 | 0.0 | 0.0 |
| QA Assistant | 1.0.0 | 1.1.0 | 996 | 994 | 0.8283 | 0.9205 | 9.22 | 1184.6 | 1526.1 | 28.83 | 20.21 | 0.0002 | 0.0009 | 486.0 | 0.0 | 0.0 |
| RAG Helpdesk | 2.0.0 | 2.1.0 | 1023 | 1008 | 0.8876 | 0.8135 | -7.41 | 2355.2 | 1984.3 | -15.75 | -26.65 | 0.0023 | 0.002 | -14.44 | 70.38 | 44.64 |

### retrieval_quality_by_version

**RAG retrieval and grounding quality by version**

- **Question:** Did a RAG release regress retrieval (Recall@K, MRR) or grounding (citation coverage, groundedness)?
- **SQL concepts:** Long-to-wide pivot of evaluation records with FILTER; joins evaluations to run facts
- **Interpretation:** Metrics are deterministic and computed against ground-truth relevant documents. MRR is the mean of per-run reciprocal ranks. Retrieval regressions usually precede answer-quality regressions.
- **Parameters:** `days=30`

```sql
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
ORDER BY m.agent_name, e.agent_version
```

Sample output - 4 row(s) shown from export, elapsed 372 ms, processed rows 416646:

| agent_name | agent_version | evaluated_runs | recall_at_k | precision_at_k | mrr | citation_coverage | groundedness | task_success_rate |
|---|---|---|---|---|---|---|---|---|
| Planner Agent | 1.0.0 | 3736 | 0.993 | 0.2483 | 0.9896 | 0.993 | 0.3073 | 0.5795 |
| Planner Agent | 2.0.0 | 3766 | 0.9973 | 0.2493 | 0.9957 | 0.9973 | 0.3392 | 0.6903 |
| RAG Helpdesk | 2.0.0 | 5825 | 0.9926 | 0.1985 | 0.9081 | 0.9561 | 0.7898 | 0.8764 |
| RAG Helpdesk | 2.1.0 | 5787 | 0.8876 | 0.2959 | 0.7944 | 0.8309 | 0.7172 | 0.7997 |

### quality_metrics_by_version

**Deterministic quality metrics by version**

- **Question:** How do schema validity, exact-match accuracy, tool correctness and hallucination indicators compare?
- **SQL concepts:** Conditional aggregation over long-format evaluation records
- **Interpretation:** All metrics here are deterministic (evaluator_type = 'deterministic'); model-judged scores, if enabled, are stored separately and never mixed into these columns.
- **Parameters:** `days=30`

```sql
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
ORDER BY agent_id, agent_version
```

Sample output - 8 row(s) shown from export, elapsed 143 ms, processed rows 324686:

| agent_id | agent_version | runs | schema_validity | exact_match | token_f1 | tool_selection_acc | tool_argument_acc | hallucination_flag_rate |
|---|---|---|---|---|---|---|---|---|
| ops-tool-agent | 1.0.0 | 5794 | 0.9886 | 0.9007 | 0.8985 | 0.9589 | 0.9335 | 0.0269 |
| ops-tool-agent | 1.1.0 | 5658 | 0.9841 | 0.8574 | 0.856 | 0.9402 | 0.9062 | 0.0474 |
| planner-agent | 1.0.0 | 5726 | 0.9895 | 0.6594 | 0.661 | 0.9461 | 0.9227 | 0.1097 |
| planner-agent | 2.0.0 | 5694 | 0.9902 | 0.759 | 0.759 | 0.9685 | 0.9517 | 0.0793 |
| qa-assistant | 1.0.0 | 5758 | 0.9894 | 0.8227 | 0.8813 | NULL | NULL | 0.052 |
| qa-assistant | 1.1.0 | 5754 | 0.9934 | 0.9163 | 0.9437 | NULL | NULL | 0.0259 |
| rag-helpdesk | 2.0.0 | 5828 | 0.9921 | 0.8765 | 0.9171 | NULL | NULL | 0.0419 |
| rag-helpdesk | 2.1.0 | 5788 | 0.9905 | 0.8003 | 0.8832 | NULL | NULL | 0.0651 |

### cost_per_successful_task

**ESTIMATED cost efficiency per successful task**

- **Question:** Which agent version delivers successful tasks most cheaply?
- **SQL concepts:** Ratio of aggregates with NULLIF guard (cost per success, not per request)
- **Interpretation:** A cheaper-per-request version can be more expensive per *successful* task if it fails more often. All monetary values are estimates from config/pricing.yaml (local, illustrative, not provider pricing).
- **Parameters:** `days=30`

```sql
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
ORDER BY estimated_cost_per_success ASC NULLS LAST
```

Sample output - 8 row(s) shown from export, elapsed 103 ms, processed rows 45980:

| agent_name | agent_version | total_estimated_cost_usd | successful_tasks | estimated_cost_per_request | estimated_cost_per_success | tokens_per_success |
|---|---|---|---|---|---|---|
| QA Assistant | 1.0.0 | 0.7423 | 4734 | 0.0001 | 0.0002 | 619.1 |
| Ops Tool Agent | 1.0.0 | 1.0777 | 5219 | 0.0002 | 0.0002 | 879.9 |
| Ops Tool Agent | 1.1.0 | 1.3923 | 4847 | 0.0002 | 0.0003 | 1191.9 |
| QA Assistant | 1.1.0 | 4.9097 | 5272 | 0.0009 | 0.0009 | 677.7 |
| RAG Helpdesk | 2.1.0 | 9.8056 | 4629 | 0.0017 | 0.0021 | 1791.5 |
| RAG Helpdesk | 2.0.0 | 12.4853 | 5107 | 0.0021 | 0.0024 | 2210.7 |
| Planner Agent | 1.0.0 | 56.6208 | 3586 | 0.0099 | 0.0158 | 4141.9 |
| Planner Agent | 2.0.0 | 74.5003 | 4202 | 0.0131 | 0.0177 | 4775.1 |

### prompt_model_comparison

**Prompt-version x model comparison**

- **Question:** How do prompt versions and model configurations compare on success, latency and tokens?
- **SQL concepts:** GROUP BY multiple dimensions joined to the agent registry (dimension table)
- **Interpretation:** Joining the registry dimension adds release dates, enabling "what changed" narratives.
- **Parameters:** `days=30`

```sql
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
ORDER BY r.released_at
```

Sample output - 8 row(s) shown from export, elapsed 170 ms, processed rows 45996:

| prompt_version | model_name | released_at | runs | success_rate | p50_ms | avg_tokens | avg_retries |
|---|---|---|---|---|---|---|---|
| qa-p1 | mock-small | 2026-08-03 | 5754 | 0.8227 | 644.3 | 509.4 | 0.032 |
| rag-p3 | mock-medium | 2026-08-10 | 5827 | 0.8764 | 1477.5 | 1937.6 | 0.033 |
| ops-p1 | mock-small | 2026-08-17 | 5793 | 0.9009 | 1215.3 | 792.7 | 0.111 |
| plan-p1 | mock-large | 2026-08-24 | 5724 | 0.6265 | 3501.0 | 2594.8 | 0.231 |
| qa-p2 | mock-medium | 2026-09-14 | 5752 | 0.9166 | 916.7 | 621.2 | 0.019 |
| rag-p4 | mock-medium | 2026-09-21 | 5788 | 0.7998 | 1284.3 | 1432.8 | 0.034 |
| ops-p2 | mock-small | 2026-09-28 | 5654 | 0.8573 | 1383.2 | 1021.8 | 0.175 |
| plan-p2 | mock-large | 2026-10-01 | 5688 | 0.7387 | 4128.4 | 3527.6 | 0.21 |


## 05_security_correlation.sql

### findings_by_rule_and_severity

**Security findings by policy rule and severity**

- **Question:** Which policy rules fire most, how severe are they, and how many attempts were blocked vs flagged?
- **SQL concepts:** Join fact to dimension (dim_policy_rules), conditional aggregation by severity and action
- **Interpretation:** 'blocked' = the runtime guard denied the action before execution; 'flagged' = detected and recorded (content-based detections cannot be blocked retroactively).
- **Parameters:** `days=30`

```sql
SELECT
    p.rule_id,
    p.rule_name,
    p.category,
    p.severity                                         AS rule_severity,
    count(f.finding_id)                                AS findings,
    count_if(f.action = 'blocked')                     AS blocked,
    count_if(f.action = 'flagged')                     AS flagged,
    count(DISTINCT f.run_id)                           AS affected_runs,
    count(DISTINCT f.agent_id)                         AS affected_agents
FROM lakehouse.analytics.dim_policy_rules p
LEFT JOIN lakehouse.analytics.agent_security_findings f
       ON f.rule_id = p.rule_id
      AND f.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY p.rule_id, p.rule_name, p.category, p.severity
ORDER BY findings DESC
```

Sample output - 8 row(s) shown from export, elapsed 144 ms, processed rows 2682:

| rule_id | rule_name | category | rule_severity | findings | blocked | flagged | affected_runs | affected_agents |
|---|---|---|---|---|---|---|---|---|
| SEC-004 | Prompt-injection indicator | prompt_injection | medium | 908 | 0 | 908 | 812 | 4 |
| SEC-001 | Tool not on agent allowlist | tool_not_allowlisted | high | 429 | 429 | 0 | 371 | 4 |
| SEC-002 | Prohibited action attempted | policy_violation | critical | 411 | 411 | 0 | 411 | 4 |
| SEC-003 | Restricted data access | restricted_data_access | high | 240 | 0 | 240 | 240 | 2 |
| SEC-005 | Sensitive data in output | sensitive_data_output | critical | 232 | 0 | 232 | 232 | 4 |
| SEC-006 | Unexpected privilege transition | privilege_escalation | critical | 208 | 0 | 208 | 208 | 4 |
| SEC-007 | Exfiltration-like sequence | exfiltration_sequence | critical | 177 | 0 | 177 | 177 | 3 |
| SEC-008 | Tool-call budget exceeded | excessive_tool_calls | medium | 69 | 69 | 0 | 68 | 2 |

### findings_with_trace_evidence

**Security findings with the span that triggered them**

- **Question:** For recent critical findings, which tool/span triggered them and what did the policy decide?
- **SQL concepts:** Multi-table join (finding -> span -> run) for evidence-linked results
- **Interpretation:** Each finding is linked to its trace and span, so an analyst can open the exact step in the trace waterfall. Evidence text is redacted for synthetic secrets.
- **Parameters:** `days=30`

```sql
SELECT
    f.event_time,
    f.rule_id,
    f.severity,
    f.agent_id,
    f.agent_version,
    f.run_id,
    f.trace_id,
    s.span_kind,
    s.span_name,
    s.tool_name,
    s.policy_decision,
    s.status          AS span_status,
    m.status          AS run_status,
    f.evidence
FROM lakehouse.analytics.agent_security_findings f
JOIN lakehouse.analytics.agent_spans s
  ON s.trace_id = f.trace_id AND s.span_id = f.span_id AND s.event_date = f.event_date
JOIN lakehouse.analytics.agent_run_metrics m
  ON m.run_id = f.run_id AND m.event_date = f.event_date
WHERE f.severity = 'critical'
  AND f.event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY f.event_time DESC
LIMIT 25
```

Sample output - 25 row(s) shown from export, elapsed 402 ms, processed rows 369685:

| event_time | rule_id | severity | agent_id | agent_version | run_id | trace_id | span_kind | span_name | tool_name | policy_decision | span_status | run_status | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-09T15:22:11.771400+00:00 | SEC-002 | critical | ops-tool-agent | 1.1.0 | R-9b7e8a-005993 | 479fcb264b57e6354920e3449543df22 | tool_call | tool:export_data | export_data | deny | error | completed | tool 'export_data' is globally prohibited |
| 2026-10-09T15:20:49.966598+00:00 | SEC-002 | critical | ops-tool-agent | 1.0.0 | R-9b7e8a-005981 | 67ccfcdcbade0a4c7272d3f1950e748c | tool_call | tool:execute_shell | execute_shell | deny | error | completed | tool 'execute_shell' is globally prohibited |
| 2026-10-09T15:20:30.060816+00:00 | SEC-007 | critical | ops-tool-agent | 1.1.0 | R-9b7e8a-005979 | 3f85860f9b5298c4e9040bba88cde1c7 | policy_check | output_guard | NULL | flag | ok | completed | sensitive read of secrets/api_keys followed by egress tool send_external_email |
| 2026-10-09T15:20:02.907889+00:00 | SEC-002 | critical | qa-assistant | 1.1.0 | R-9b7e8a-005975 | e65fa452b45cc2d328685d9b991d8d55 | tool_call | tool:export_data | export_data | deny | error | completed | tool 'export_data' is globally prohibited |
| 2026-10-09T15:19:34.634960+00:00 | SEC-005 | critical | planner-agent | 2.0.0 | R-9b7e8a-005970 | 61f03cb380aa505861465d5b14eed677 | policy_check | output_guard | NULL | flag | ok | completed | synthetic_api_key pattern in output: sk-ags******************* |
| 2026-10-09T15:19:33.322147+00:00 | SEC-005 | critical | rag-helpdesk | 2.0.0 | R-9b7e8a-005971 | cd44279d58edccb5ca045c3ad8de9284 | policy_check | output_guard | NULL | flag | ok | completed | canary_token pattern in output: AGSH-C************** |
| 2026-10-09T15:17:55.539183+00:00 | SEC-006 | critical | qa-assistant | 1.1.0 | R-315910-019976 | 9d15170cbad6362ac96a84caf2c15add | policy_check | role_monitor | NULL | flag | ok | completed | runtime role changed agent_runtime -> root |
| 2026-10-09T15:17:23.252944+00:00 | SEC-002 | critical | planner-agent | 2.0.0 | R-9b7e8a-005953 | ea7811211360c8532f2002e4353b5b7f | tool_call | tool:modify_permissions | modify_permissions | deny | error | completed | tool 'modify_permissions' is globally prohibited |
| 2026-10-09T15:17:23.249445+00:00 | SEC-006 | critical | planner-agent | 2.0.0 | R-9b7e8a-005953 | ea7811211360c8532f2002e4353b5b7f | policy_check | role_monitor | NULL | flag | ok | completed | runtime role changed agent_runtime -> security_admin |
| 2026-10-09T15:15:09.001426+00:00 | SEC-002 | critical | qa-assistant | 1.0.0 | R-9b7e8a-005934 | 8f0de8e18c1a98a5b9dcf3547dba3402 | tool_call | tool:delete_records | delete_records | deny | error | completed | tool 'delete_records' is globally prohibited |
| 2026-10-09T15:14:20.844533+00:00 | SEC-002 | critical | planner-agent | 1.0.0 | R-9b7e8a-005927 | 14f445d5897ed9037cf550c12f97fb69 | tool_call | tool:export_data | export_data | deny | error | completed | tool 'export_data' is globally prohibited |
| 2026-10-09T15:12:27.173729+00:00 | SEC-002 | critical | qa-assistant | 1.1.0 | R-9b7e8a-005912 | bc4abcd7a4db8ddc7ff114ce599b106a | tool_call | tool:export_data | export_data | deny | error | completed | tool 'export_data' is globally prohibited |

_13 more rows not shown (full result in docs/sql_outputs)._

### anomaly_security_correlation

**Runs with anomaly alerts and/or security findings**

- **Question:** Which runs were both anomalous (performance) and security-relevant?
- **SQL concepts:** LEFT JOINs across three fact tables on (run_id, trace_id)
- **Interpretation:** Overlap is a strong investigation signal (e.g. a loop that also exceeded the tool budget). Correlation is not causation, and an anomaly is not automatically an attack.
- **Parameters:** `days=30`

```sql
SELECT
    m.run_id,
    m.trace_id,
    m.agent_name,
    m.agent_version,
    m.latency_ms,
    m.output_tokens,
    a.anomaly_type,
    a.severity AS anomaly_severity,
    s.rule_id,
    s.severity AS security_severity
FROM lakehouse.analytics.agent_run_metrics m
LEFT JOIN lakehouse.analytics.agent_anomaly_alerts a
       ON m.run_id = a.run_id
      AND m.trace_id = a.trace_id
LEFT JOIN lakehouse.analytics.agent_security_findings s
       ON m.run_id = s.run_id
      AND m.trace_id = s.trace_id
WHERE (a.alert_id IS NOT NULL OR s.finding_id IS NOT NULL)
  AND m.event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY (a.alert_id IS NOT NULL AND s.finding_id IS NOT NULL) DESC, m.event_time DESC
LIMIT 50
```

Sample output - 50 row(s) shown from export, elapsed 150 ms, processed rows 51328:

| run_id | trace_id | agent_name | agent_version | latency_ms | output_tokens | anomaly_type | anomaly_severity | rule_id | security_severity |
|---|---|---|---|---|---|---|---|---|---|
| R-9b7e8a-005993 | 479fcb264b57e6354920e3449543df22 | Ops Tool Agent | 1.1.0 | 1324.701 | 183 | NULL | NULL | SEC-004 | medium |
| R-9b7e8a-005993 | 479fcb264b57e6354920e3449543df22 | Ops Tool Agent | 1.1.0 | 1324.701 | 183 | NULL | NULL | SEC-002 | critical |
| R-9b7e8a-005992 | 04ca46140bc533a4734dc91acd8a2255 | Ops Tool Agent | 1.1.0 | 1811.048 | 278 | NULL | NULL | SEC-001 | high |
| R-9b7e8a-005982 | 9110baf7231a5e2e774bcb593cb9a182 | Planner Agent | 1.0.0 | 3252.925 | 363 | NULL | NULL | SEC-001 | high |
| R-9b7e8a-005981 | 67ccfcdcbade0a4c7272d3f1950e748c | Ops Tool Agent | 1.0.0 | 1138.275 | 113 | NULL | NULL | SEC-002 | critical |
| R-9b7e8a-005979 | 3f85860f9b5298c4e9040bba88cde1c7 | Ops Tool Agent | 1.1.0 | 990.603 | 161 | NULL | NULL | SEC-001 | high |
| R-9b7e8a-005979 | 3f85860f9b5298c4e9040bba88cde1c7 | Ops Tool Agent | 1.1.0 | 990.603 | 161 | NULL | NULL | SEC-001 | high |
| R-9b7e8a-005979 | 3f85860f9b5298c4e9040bba88cde1c7 | Ops Tool Agent | 1.1.0 | 990.603 | 161 | NULL | NULL | SEC-007 | critical |
| R-9b7e8a-005978 | a2c7063b64dc89add967d05636a0cdd7 | RAG Helpdesk | 2.0.0 | 1173.025 | 180 | NULL | NULL | SEC-004 | medium |
| R-9b7e8a-005975 | e65fa452b45cc2d328685d9b991d8d55 | QA Assistant | 1.1.0 | 701.404 | 164 | NULL | NULL | SEC-004 | medium |
| R-9b7e8a-005975 | e65fa452b45cc2d328685d9b991d8d55 | QA Assistant | 1.1.0 | 701.404 | 164 | NULL | NULL | SEC-002 | critical |
| R-9b7e8a-005974 | c8b547c651fc80bfaf5bb6f3f5e073e2 | Ops Tool Agent | 1.1.0 | 1773.272 | 194 | NULL | NULL | SEC-001 | high |

_38 more rows not shown (full result in docs/sql_outputs)._

### window_correlation_perf_errors_security

**Hourly correlation of latency regressions, tool errors and security findings**

- **Question:** In which hours did tail latency spike, and did tool errors or security findings rise at the same time?
- **SQL concepts:** Time-window join of three aggregated CTEs; corr() statistical aggregate
- **Interpretation:** Joining on (agent, hour) aligns signals that live in different tables. corr() quantifies how strongly hourly tool errors track hourly p95 latency across all windows.
- **Parameters:** `days=30, agent_id='ops-tool-agent'`

```sql
WITH perf AS (
    SELECT agent_id, agent_version, date_trunc('hour', event_time) AS hour,
           count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95_ms
    FROM lakehouse.analytics.agent_run_metrics
    WHERE agent_id = :agent_id AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
tool_err AS (
    SELECT agent_id, agent_version, date_trunc('hour', event_time) AS hour,
           count_if(status <> 'ok' AND tool_allowed) AS tool_failures
    FROM lakehouse.analytics.agent_spans
    WHERE span_kind = 'tool_call' AND agent_id = :agent_id
      AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
sec AS (
    SELECT agent_id, agent_version, date_trunc('hour', event_time) AS hour, count(*) AS findings
    FROM lakehouse.analytics.agent_security_findings
    WHERE agent_id = :agent_id AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
joined AS (
    SELECT p.agent_version, p.hour, p.runs, p.p95_ms,
           coalesce(t.tool_failures, 0) AS tool_failures,
           coalesce(s.findings, 0)      AS findings
    FROM perf p
    LEFT JOIN tool_err t ON t.agent_id = p.agent_id AND t.agent_version = p.agent_version AND t.hour = p.hour
    LEFT JOIN sec s      ON s.agent_id = p.agent_id AND s.agent_version = p.agent_version AND s.hour = p.hour
)
SELECT
    agent_version,
    hour,
    runs,
    round(p95_ms, 1)                                                          AS p95_ms,
    tool_failures,
    findings,
    round(corr(p95_ms, tool_failures) OVER (PARTITION BY agent_version), 3)  AS corr_p95_vs_tool_failures
FROM joined
ORDER BY tool_failures DESC, p95_ms DESC
LIMIT 20
```

Sample output - 20 row(s) shown from export, elapsed 222 ms, processed rows 351234:

| agent_version | hour | runs | p95_ms | tool_failures | findings | corr_p95_vs_tool_failures |
|---|---|---|---|---|---|---|
| 1.1.0 | 2026-10-09T07:00:00+00:00 | 213 | 2084.0 | 46 | 12 | 0.138 |
| 1.1.0 | 2026-10-08T12:00:00+00:00 | 39 | 2948.6 | 45 | 0 | 0.138 |
| 1.1.0 | 2026-10-09T10:00:00+00:00 | 258 | 2129.1 | 43 | 15 | 0.138 |
| 1.1.0 | 2026-10-09T04:00:00+00:00 | 232 | 2046.8 | 40 | 20 | 0.138 |
| 1.1.0 | 2026-10-09T00:00:00+00:00 | 89 | 2564.1 | 39 | 1 | 0.138 |
| 1.1.0 | 2026-10-09T14:00:00+00:00 | 228 | 2124.6 | 34 | 10 | 0.138 |
| 1.1.0 | 2026-10-09T06:00:00+00:00 | 237 | 2377.8 | 33 | 36 | 0.138 |
| 1.1.0 | 2026-10-09T05:00:00+00:00 | 242 | 1997.9 | 32 | 11 | 0.138 |
| 1.1.0 | 2026-10-09T08:00:00+00:00 | 265 | 2204.2 | 30 | 30 | 0.138 |
| 1.1.0 | 2026-10-09T03:00:00+00:00 | 184 | 2118.4 | 30 | 7 | 0.138 |
| 1.1.0 | 2026-10-09T09:00:00+00:00 | 256 | 2049.4 | 30 | 16 | 0.138 |
| 1.0.0 | 2026-10-09T06:00:00+00:00 | 255 | 1853.0 | 30 | 30 | 0.006 |

_8 more rows not shown (full result in docs/sql_outputs)._

### exfiltration_sequences

**Traces with a sensitive read followed by an egress attempt**

- **Question:** Which traces show a restricted-data access followed later by an egress tool attempt?
- **SQL concepts:** Sequence analysis with conditional MIN() per trace and a HAVING ordering constraint
- **Interpretation:** Reconstructs the exfiltration pattern in SQL from span facts independently of the runtime detector (SEC-007), which is a useful cross-check of the detector.
- **Parameters:** `days=30`

```sql
SELECT
    trace_id,
    min(run_id)                                                                                    AS run_id,
    min(agent_id)                                                                                  AS agent_id,
    min(start_time) FILTER (WHERE data_classification IN ('confidential', 'restricted')
                              AND span_kind IN ('tool_call', 'retrieval'))                         AS first_sensitive_read,
    min(start_time) FILTER (WHERE tool_name IN ('send_external_email', 'http_post', 'export_data')) AS first_egress_attempt,
    array_join(array_agg(DISTINCT tool_name) FILTER (WHERE tool_name IS NOT NULL), ',')           AS tools_used
FROM lakehouse.analytics.agent_spans
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY trace_id
HAVING min(start_time) FILTER (WHERE data_classification IN ('confidential', 'restricted')
                                 AND span_kind IN ('tool_call', 'retrieval'))
     < min(start_time) FILTER (WHERE tool_name IN ('send_external_email', 'http_post', 'export_data'))
ORDER BY first_egress_attempt DESC
LIMIT 25
```

Sample output - 25 row(s) shown from export, elapsed 231 ms, processed rows 302580:

| trace_id | run_id | agent_id | first_sensitive_read | first_egress_attempt | tools_used |
|---|---|---|---|---|---|
| 3f85860f9b5298c4e9040bba88cde1c7 | R-9b7e8a-005979 | ops-tool-agent | 2026-10-09T15:20:29.411514+00:00 | 2026-10-09T15:20:29.417436+00:00 | read_resource,send_external_email,get_order_status |
| b51a7908730ec2483bfe847192f64256 | R-9b7e8a-005858 | rag-helpdesk | 2026-10-09T15:06:00.971470+00:00 | 2026-10-09T15:06:01.136796+00:00 | document_lookup,http_post |
| eef0bdefdb5e60f909ad4fc6b9df23e3 | R-9b7e8a-005839 | rag-helpdesk | 2026-10-09T15:03:42.306654+00:00 | 2026-10-09T15:03:42.420055+00:00 | document_lookup,send_external_email |
| ba8a7ed1e106c76b8079e7918bd54bf8 | R-9b7e8a-005833 | ops-tool-agent | 2026-10-09T15:03:04.344376+00:00 | 2026-10-09T15:03:04.348976+00:00 | read_resource,send_external_email,get_order_status |
| 64387842af75fd888e3ca9dd28427477 | R-9b7e8a-005784 | rag-helpdesk | 2026-10-09T14:57:11.432137+00:00 | 2026-10-09T14:57:11.773881+00:00 | document_lookup,http_post |
| d7d7d0cb0075dccc126ea630910789c8 | R-9b7e8a-005670 | rag-helpdesk | 2026-10-09T14:43:25.460854+00:00 | 2026-10-09T14:43:25.565882+00:00 | document_lookup,http_post |
| 313ebb2723888bf8e09589ed87600a90 | R-9b7e8a-005661 | rag-helpdesk | 2026-10-09T14:42:26.403238+00:00 | 2026-10-09T14:42:26.505071+00:00 | document_lookup,http_post |
| 551233d1fe538378b9151611af4e7ea4 | R-9b7e8a-005533 | planner-agent | 2026-10-09T14:27:00.175758+00:00 | 2026-10-09T14:27:00.335592+00:00 | document_lookup,http_post,search_kb,calculator |
| fe769b3d2e8307d2b9ddf9ff3429ba02 | R-9b7e8a-005260 | rag-helpdesk | 2026-10-09T13:54:16.122464+00:00 | 2026-10-09T13:54:16.256653+00:00 | document_lookup,http_post |
| c573468ab2d0074602b6442fe706f53f | R-9b7e8a-005236 | planner-agent | 2026-10-09T13:51:26.821760+00:00 | 2026-10-09T13:51:26.950224+00:00 | document_lookup,send_external_email,get_order_status |
| bfd2edf210f4193b28b403f1868f52e1 | R-9b7e8a-005222 | ops-tool-agent | 2026-10-09T13:49:41.173768+00:00 | 2026-10-09T13:49:41.179223+00:00 | read_resource,http_post,search_kb |
| 306b9c0495f036929f314712c1142b92 | R-9b7e8a-005216 | planner-agent | 2026-10-09T13:48:57.131245+00:00 | 2026-10-09T13:48:57.348658+00:00 | document_lookup,send_external_email,search_kb,calculator |

_13 more rows not shown (full result in docs/sql_outputs)._

### security_detection_vs_ground_truth

**Security rule detection rate and false positives vs synthetic ground truth**

- **Question:** For each injected security scenario, how often did the expected rule category fire, and how many findings occurred on runs with no injected security scenario?
- **SQL concepts:** UNNEST of label arrays, LEFT JOIN, confusion-matrix style conditional aggregation
- **Interpretation:** Ground truth = injected_faults labels written by the generator (never used by detectors). 'poisoned_document_retrieved' marks runs that retrieved a poisoned KB document without an injected fault - prompt-injection findings there are true detections, not false positives.
- **Parameters:** `days=30`

```sql
WITH labels AS (
    SELECT m.run_id, f AS label
    FROM lakehouse.analytics.agent_run_metrics m
    CROSS JOIN UNNEST(m.injected_faults) AS t(f)
    WHERE m.event_date >= current_date - (:days * INTERVAL '1' DAY)
),
expected AS (
    SELECT * FROM (VALUES
        ('suspicious_tool_access', 'tool_not_allowlisted'),
        ('policy_violation', 'policy_violation'),
        ('prompt_injection', 'prompt_injection'),
        ('poisoned_document_retrieved', 'prompt_injection'),
        ('sensitive_data_leak', 'sensitive_data_output'),
        ('exfiltration_sequence', 'exfiltration_sequence'),
        ('privilege_escalation', 'privilege_escalation')
    ) AS e(label, category)
),
found AS (
    SELECT DISTINCT run_id, category FROM lakehouse.analytics.agent_security_findings
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
),
per_label AS (
    SELECT e.label, e.category, count(*) AS labelled_runs, count(f.run_id) AS detected_runs
    FROM labels l
    JOIN expected e ON e.label = l.label
    LEFT JOIN found f ON f.run_id = l.run_id AND f.category = e.category
    GROUP BY e.label, e.category
),
unlabelled AS (
    SELECT f.category, count(DISTINCT f.run_id) AS runs_with_finding
    FROM found f
    WHERE NOT EXISTS (SELECT 1 FROM labels l JOIN expected e ON e.label = l.label WHERE l.run_id = f.run_id)
    GROUP BY f.category
)
SELECT
    p.label                                                   AS injected_scenario,
    p.category                                                AS expected_category,
    p.labelled_runs,
    p.detected_runs,
    round(100e0 * p.detected_runs / p.labelled_runs, 2)       AS detection_rate_pct,
    coalesce(u.runs_with_finding, 0)                          AS same_category_findings_on_unlabelled_runs
FROM per_label p
LEFT JOIN unlabelled u ON u.category = p.category
ORDER BY p.label
```

Sample output - 7 row(s) shown from export, elapsed 238 ms, processed rows 99841:

| injected_scenario | expected_category | labelled_runs | detected_runs | detection_rate_pct | same_category_findings_on_unlabelled_runs |
|---|---|---|---|---|---|
| exfiltration_sequence | exfiltration_sequence | 177 | 177 | 100.0 | 0 |
| poisoned_document_retrieved | prompt_injection | 593 | 592 | 99.83 | 0 |
| policy_violation | policy_violation | 224 | 224 | 100.0 | 0 |
| privilege_escalation | privilege_escalation | 208 | 208 | 100.0 | 0 |
| prompt_injection | prompt_injection | 220 | 220 | 100.0 | 0 |
| sensitive_data_leak | sensitive_data_output | 232 | 232 | 100.0 | 0 |
| suspicious_tool_access | tool_not_allowlisted | 194 | 194 | 100.0 | 0 |


## 06_data_quality_checks.sql

### dq_scorecard

**Data-quality scorecard (one row per check)**

- **Question:** How healthy is the curated data overall?
- **SQL concepts:** CTE per check + UNION ALL into a single scorecard
- **Interpretation:** issue_rate_pct is issues / rows checked. Non-zero counts are expected when a scenario injects dirty data (dirty_rate > 0); compare them with the generator's dirty_injected summary.
- **Parameters:** `days=30`

```sql
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
ORDER BY issues DESC
```

Sample output - 7 row(s) shown from export, elapsed 582 ms, processed rows 3773355:

| check_name | issues | rows_checked | issue_rate_pct | result |
|---|---|---|---|---|
| quarantined_records | 446 | 676374 | 0.0659 | REVIEW |
| orphan_spans | 205 | 256611 | 0.0799 | REVIEW |
| duplicate_event_ids | 90 | 675928 | 0.0133 | REVIEW |
| negative_span_durations | 36 | 302580 | 0.0119 | REVIEW |
| future_event_times | 0 | 302580 | 0.0 | PASS |
| end_before_start | 0 | 302580 | 0.0 | PASS |
| null_trace_ids_in_spans | 0 | 302580 | 0.0 | PASS |

### dq_null_ids

**Null identifiers per curated table**

- **Question:** Do any curated rows lack the shared keys every module relies on?
- **SQL concepts:** Conditional aggregation across UNION ALL of several fact tables
- **Interpretation:** Spark rejects events missing required context, so these should be zero; a non-zero value would indicate a contract change that bypassed validation.
- **Parameters:** `days=30`

```sql
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
FROM lakehouse.analytics.agent_security_findings WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
```

Sample output - 4 row(s) shown from export, elapsed 140 ms, processed rows 675920:

| table_name | rows_checked | null_event_id | null_run_id | null_trace_id | null_agent_id |
|---|---|---|---|---|---|
| agent_security_findings | 2674 | 0 | 0 | 0 | 0 |
| agent_run_metrics | 45980 | 0 | 0 | 0 | 0 |
| agent_evaluation_results | 324686 | 0 | 0 | 0 | 0 |
| agent_spans | 302580 | 0 | 0 | 0 | 0 |

### dq_duplicate_events

**Duplicate event IDs (at-least-once delivery / producer retries)**

- **Question:** Which event IDs were ingested more than once, and on which topics?
- **SQL concepts:** GROUP BY ... HAVING count(*) > 1
- **Interpretation:** Duplicates are expected under at-least-once delivery. Analytical queries that must be exact can de-duplicate with ROW_NUMBER() OVER (PARTITION BY event_id ...).
- **Parameters:** `days=30`

```sql
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
ORDER BY extra_copies DESC
```

Sample output - 3 row(s) shown from export, elapsed 461 ms, processed rows 676374:

| kafka_topic | event_type | duplicated_event_ids | extra_copies |
|---|---|---|---|
| agent-evaluations | evaluation.result | 48 | 48 |
| agent-traces | span.completed | 33 | 33 |
| agent-metrics | run.metrics | 9 | 9 |

### dq_orphan_spans

**Spans whose parent span is missing**

- **Question:** Which traces contain spans pointing to a parent that never arrived (or was quarantined)?
- **SQL concepts:** Anti-join (LEFT JOIN ... WHERE right side IS NULL)
- **Interpretation:** Orphans break the trace waterfall. Causes: corrupted parent IDs, or a parent event that was quarantined as structurally invalid (check dead_letter_events for the same trace).
- **Parameters:** `days=30`

```sql
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
ORDER BY orphan_spans DESC
```

Sample output - 1 row(s) shown from export, elapsed 907 ms, processed rows 907740:

| test_run_id | orphan_spans | affected_traces | example_trace_id |
|---|---|---|---|
| TR-20261009-315910 | 205 | 67 | 01d9b1700eb498726081963a50a4c37d |

### dq_quarantine_reasons

**Quarantined (dead-letter) records by reason and day**

- **Question:** Why were records rejected by the stream processor, and is the rejection rate stable?
- **SQL concepts:** Aggregation over the dead-letter table
- **Interpretation:** Every rejected record is kept (raw bytes + reason) - nothing is silently dropped.
- **Parameters:** `days=30`

```sql
SELECT
    ingest_date,
    validation_error,
    kafka_topic,
    count(*) AS records
FROM lakehouse.analytics.dead_letter_events
WHERE ingest_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY ingest_date, validation_error, kafka_topic
ORDER BY ingest_date DESC, records DESC
```

Sample output - 14 row(s) shown from export, elapsed 259 ms, processed rows 446:

| ingest_date | validation_error | kafka_topic | records |
|---|---|---|---|
| 2026-10-09 | unknown_event_type | agent-evaluations | 68 |
| 2026-10-09 | malformed_json | agent-evaluations | 64 |
| 2026-10-09 | invalid_event_time | agent-evaluations | 62 |
| 2026-10-09 | missing_event_id | agent-evaluations | 59 |
| 2026-10-09 | unknown_event_type | agent-traces | 45 |
| 2026-10-09 | missing_event_id | agent-traces | 43 |
| 2026-10-09 | malformed_json | agent-traces | 40 |
| 2026-10-09 | invalid_event_time | agent-traces | 35 |
| 2026-10-09 | invalid_event_time | agent-metrics | 11 |
| 2026-10-09 | unknown_event_type | agent-metrics | 7 |
| 2026-10-09 | missing_event_id | agent-metrics | 5 |
| 2026-10-09 | malformed_json | agent-metrics | 3 |

_2 more rows not shown (full result in docs/sql_outputs)._

### dq_timestamp_checks

**Timestamp sanity: span ordering, clock skew and run-window consistency**

- **Question:** Are event timestamps plausible (ordered, not in the future, inside their test run's window)?
- **SQL concepts:** Interval arithmetic, joins to the test-run dimension
- **Interpretation:** For simulated runs event_time lies in the test run's simulated window; for realtime runs it lies between started_at and ended_at. Events outside indicate producer clock problems.
- **Parameters:** `days=30`

```sql
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
ORDER BY runs DESC
```

Sample output - 4 row(s) shown from export, elapsed 281 ms, processed rows 45988:

| test_run_id | time_mode | runs | end_before_start | future_events | outside_sim_window | avg_event_to_ingest_ms_realtime |
|---|---|---|---|---|---|---|
| TR-20261009-315910 | simulated | 19980 | 0 | 0 | 0 | NULL |
| TR-20261009-12eb56 | simulated | 12000 | 0 | 0 | 0 | NULL |
| TR-20261009-23c1c6 | simulated | 8000 | 0 | 0 | 0 | NULL |
| TR-20261009-9b7e8a | simulated | 6000 | 0 | 0 | 0 | NULL |

### dq_run_span_consistency

**Run summary vs span facts consistency**

- **Question:** Does each run's reported span_count match the spans actually stored?
- **SQL concepts:** Join an aggregate of child facts back to the parent fact
- **Interpretation:** Mismatches indicate lost or duplicated span events (e.g. a quarantined span or a duplicate).
- **Parameters:** `days=30`

```sql
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
ORDER BY runs DESC
```

Sample output - 4 row(s) shown from export, elapsed 433 ms, processed rows 394560:

| test_run_id | runs | consistent_runs | runs_missing_spans | runs_with_extra_spans | consistency_pct |
|---|---|---|---|---|---|
| TR-20261009-315910 | 19980 | 19818 | 162 | 0 | 99.189 |
| TR-20261009-12eb56 | 12000 | 12000 | 0 | 0 | 100.0 |
| TR-20261009-23c1c6 | 8000 | 8000 | 0 | 0 | 100.0 |
| TR-20261009-9b7e8a | 6000 | 6000 | 0 | 0 | 100.0 |


## 07_summary_tables.sql

### summary_vs_raw_consistency

**Summary table vs raw facts consistency check**

- **Question:** Do the pre-aggregated daily summaries agree with a direct aggregation of the fact table?
- **SQL concepts:** Reconciliation of a materialised aggregate against its source
- **Interpretation:** Counts must match exactly. Percentiles may differ slightly: the summary's are merged T-Digest sketches, the direct ones approx_percentile digests; both are approximations of the exact value.
- **Parameters:** `days=60`

```sql
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
LIMIT 20
```

Sample output - 20 row(s) shown from export, elapsed 142 ms, processed rows 46012:

| event_date | agent_id | agent_version | runs_direct | runs_summary | successes_match | p95_direct | p95_from_merged_tdigest | p95_diff_pct |
|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | rag-helpdesk | 2.1.0 | 3238 | 3238 | True | 2156.5 | 2160.3 | 0.18 |
| 2026-10-09 | ops-tool-agent | 1.0.0 | 3256 | 3256 | True | 1866.3 | 1868.1 | 0.09 |
| 2026-10-09 | planner-agent | 1.0.0 | 3268 | 3268 | True | 5740.5 | 5727.7 | -0.22 |
| 2026-10-09 | rag-helpdesk | 2.0.0 | 3323 | 3323 | True | 2655.7 | 2663.0 | 0.27 |
| 2026-10-09 | planner-agent | 2.0.0 | 3263 | 3263 | True | 6540.5 | 6538.5 | -0.03 |
| 2026-10-09 | ops-tool-agent | 1.1.0 | 3154 | 3154 | True | 2116.1 | 2130.0 | 0.65 |
| 2026-10-09 | qa-assistant | 1.1.0 | 3273 | 3273 | True | 1586.6 | 1597.6 | 0.7 |
| 2026-10-09 | qa-assistant | 1.0.0 | 3187 | 3187 | True | 1178.9 | 1183.9 | 0.42 |
| 2026-10-08 | ops-tool-agent | 1.1.0 | 1351 | 1351 | True | 2852.4 | 2816.1 | -1.27 |
| 2026-10-08 | qa-assistant | 1.1.0 | 1350 | 1350 | True | 1575.3 | 1583.4 | 0.51 |
| 2026-10-08 | rag-helpdesk | 2.1.0 | 1385 | 1385 | True | 2284.9 | 2294.7 | 0.43 |
| 2026-10-08 | rag-helpdesk | 2.0.0 | 1378 | 1378 | True | 2623.5 | 2642.8 | 0.74 |

_8 more rows not shown (full result in docs/sql_outputs)._

### daily_trend_from_summary

**Daily success, p95 latency and estimated cost trend (from the summary table)**

- **Question:** How do daily success rate, p95 latency and estimated cost evolve per agent version?
- **SQL concepts:** Querying a pre-aggregated table; LAG for day-over-day change
- **Interpretation:** Reads only a few hundred summary rows instead of millions of facts - the summary-table pattern.
- **Parameters:** `days=60`

```sql
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
ORDER BY agent_name, agent_version, event_date
```

Sample output - 32 row(s) shown from export, elapsed 90 ms, processed rows 32:

| event_date | agent_name | agent_version | runs | success_rate | p95_latency_ms | est_cost_usd | security_findings | success_delta_vs_prev_day |
|---|---|---|---|---|---|---|---|---|
| 2026-10-06 | Ops Tool Agent | 1.0.0 | 316 | 0.9051 | 1663.7 | 0.0564 | 9 | NULL |
| 2026-10-07 | Ops Tool Agent | 1.0.0 | 837 | 0.8889 | 1760.0 | 0.1555 | 23 | -0.0162 |
| 2026-10-08 | Ops Tool Agent | 1.0.0 | 1384 | 0.8981 | 1978.2 | 0.258 | 27 | 0.0092 |
| 2026-10-09 | Ops Tool Agent | 1.0.0 | 3256 | 0.9048 | 1868.1 | 0.6079 | 230 | 0.0067 |
| 2026-10-06 | Ops Tool Agent | 1.1.0 | 326 | 0.8926 | 2151.0 | 0.0778 | 9 | NULL |
| 2026-10-07 | Ops Tool Agent | 1.1.0 | 823 | 0.8591 | 2028.5 | 0.2008 | 24 | -0.0336 |
| 2026-10-08 | Ops Tool Agent | 1.1.0 | 1351 | 0.849 | 2816.1 | 0.3394 | 27 | -0.0101 |
| 2026-10-09 | Ops Tool Agent | 1.1.0 | 3154 | 0.8567 | 2130.0 | 0.7743 | 222 | 0.0077 |
| 2026-10-06 | Planner Agent | 1.0.0 | 287 | 0.6237 | 6180.9 | 2.8564 | 5 | NULL |
| 2026-10-07 | Planner Agent | 1.0.0 | 805 | 0.6248 | 5789.1 | 7.8741 | 14 | 0.0012 |
| 2026-10-08 | Planner Agent | 1.0.0 | 1364 | 0.6188 | 6069.4 | 13.6504 | 9 | -0.0061 |
| 2026-10-09 | Planner Agent | 1.0.0 | 3268 | 0.6304 | 5727.7 | 32.2399 | 264 | 0.0116 |

_20 more rows not shown (full result in docs/sql_outputs)._


## 08_query_plan_experiments.sql

### plan_partition_pruning

**EXPLAIN - partition pruning on event_date**

- **Question:** Does a filter on the partition column limit which data files Trino scans?
- **SQL concepts:** EXPLAIN (TYPE DISTRIBUTED); Iceberg partition pruning; predicate pushdown
- **Interpretation:** Look for the event_date constraint pushed into the TableScan (connector-level constraint). Iceberg prunes whole partitions (and files by min/max stats) before any Parquet is read. (Literal filter: Trino does not bind prepared-statement parameters inside EXPLAIN (TYPE ...).)
- **Parameters:** `none`

```sql
EXPLAIN (TYPE DISTRIBUTED)
SELECT agent_id, count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - INTERVAL '1' DAY
GROUP BY agent_id
```

Sample output - 1 row(s) shown from export, elapsed 85 ms, processed rows 0:

```text
Trino version: 467
Fragment 0 [HASH]
    Output layout: [agent_id, count, approx_percentile]
    Output partitioning: SINGLE []
    Output[columnNames = [agent_id, runs, p95]]
    │   Layout: [agent_id:varchar, count:bigint, approx_percentile:double]
    │   Estimates: {rows: ? (?), cpu: 0, memory: 0B, network: 0B}
    │   runs := count
    │   p95 := approx_percentile
    └─ Aggregate[type = FINAL, keys = [agent_id]]
       │   Layout: [agent_id:varchar, count:bigint, approx_percentile:double]
       │   Estimates: {rows: ? (?), cpu: 2.46M, memory: ?, network: 0B}
       │   count := count(count_1)
       │   approx_percentile := approx_percentile(approx_percentile_2)
       └─ LocalExchange[partitioning = HASH, arguments = [agent_id::varchar]]
          │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
          │   Estimates: {rows: 36929 (2.46MB), cpu: 2.46M, memory: 0B, network: 0B}
          └─ RemoteSource[sourceFragmentIds = [1]]
                 Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]

Fragment 1 [SOURCE]
    Output layout: [agent_id, count_1, approx_percentile_2]
    Output partitioning: HASH [agent_id]
    Aggregate[type = PARTIAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
    │   Estimates: {rows: 36929 (2.46MB), cpu: ?, memory: ?, network: ?}
    │   count_1 := count(*)
    │   approx_percentile_2 := approx_percentile(latency_ms, expr_0)
    └─ ScanProject[table = lakehouse:analytics.agent_run_metrics$data@1920632619667562006 constraint on [event_date]]
           Layout: [latency_ms:double, expr_0:double, agent_id:varchar]
           Estimates: {rows: 36929 (855.85kB), cpu: 531.28k, memory: 0B, network: 0B}/{rows: 36929 (855.85kB), cpu: 855.85k, memory: 0B, network: 0B}
           expr_0 := double '0.95'
           latency_ms := 21:latency_ms:double
           agent_id := 5:agent_id:varchar
           20:event_date:date
               :: [[2026-10-08, <max>)]


```

### analyze_with_partition_filter

**EXPLAIN ANALYZE - one day of data (partition filter)**

- **Question:** How many rows and bytes are physically read when filtering on the partition column?
- **SQL concepts:** EXPLAIN ANALYZE (actual rows/bytes read per operator)
- **Interpretation:** Compare 'Input:' rows/bytes of the ScanFilter operator with analyze_without_partition_filter.
- **Parameters:** `days=0`

```sql
EXPLAIN ANALYZE
SELECT agent_id, count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY agent_id
```

Sample output - 1 row(s) shown from export, elapsed 185 ms, processed rows 25962:

```text
Trino version: 467
Queued: 190.36us, Analysis: 14.40ms, Planning: 24.07ms, Execution: 163.55ms
Fragment 1 [HASH]
    CPU: 4.85ms, Scheduled: 7.99ms, Blocked 669.82ms (Input: 336.51ms, Output: 0.00ns), Input: 12 rows (10.88kB); per task: avg.: 12.00 std.dev.: 0.00, Output: 4 rows (143B)
    Peak Memory: 1.88kB, Tasks count: 1; per task: max: 1.29MB
    Output layout: [agent_id, count, approx_percentile]
    Output partitioning: SINGLE []
    Aggregate[type = FINAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count:bigint, approx_percentile:double]
    │   Estimates: {rows: ? (?), cpu: 1.73M, memory: ?, network: 0B}
    │   CPU: 2.00ms (15.38%), Scheduled: 2.00ms (10.53%), Blocked: 0.00ns (0.00%), Output: 4 rows (143B)
    │   Input avg.: 0.75 rows, Input std.dev.: 300.00%
    │   count := count(count_1)
    │   approx_percentile := approx_percentile(approx_percentile_2)
    └─ LocalExchange[partitioning = HASH, arguments = [agent_id::varchar]]
       │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
       │   Estimates: {rows: 25962 (1.73MB), cpu: 1.73M, memory: 0B, network: 0B}
       │   CPU: 1.00ms (7.69%), Scheduled: 1.00ms (5.26%), Blocked: 333.00ms (49.70%), Output: 12 rows (10.88kB)
       │   Input avg.: 0.75 rows, Input std.dev.: 208.17%
       └─ RemoteSource[sourceFragmentIds = [2]]
              Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
              CPU: 0.00ns (0.00%), Scheduled: 2.00ms (10.53%), Blocked: 337.00ms (50.30%), Output: 12 rows (10.88kB)
              Input avg.: 0.75 rows, Input std.dev.: 208.17%

Fragment 2 [SOURCE]
    CPU: 11.07ms, Scheduled: 14.84ms, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 25962 rows (332.03kB); per task: avg.: 25962.00 std.dev.: 0.00, Output: 12 rows (10.88kB)
    Peak Memory: 2.20MB, Tasks count: 1; per task: max: 2.80MB
    Output layout: [agent_id, count_1, approx_percentile_2]
    Output partitioning: HASH [agent_id]
    Aggregate[type = PARTIAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
    │   Estimates: {rows: 25962 (1.73MB), cpu: ?, memory: ?, network: ?}
    │   CPU: 5.00ms (38.46%), Scheduled: 6.00ms (31.58%), Blocked: 0.00ns (0.00%), Output: 12 rows (10.88kB)
    │   Input avg.: 8654.00 rows, Input std.dev.: 60.66%
    │   count_1 := count(*)
    │   approx_percentile_2 := approx_percentile(latency_ms, expr_0)
    └─ ScanProject[table = lakehouse:analytics.agent_run_metrics$data@1920632619667562006 constraint on [event_date]]
           Layout: [latency_ms:double, expr_0:double, agent_id:varchar]
           Estimates: {rows: 25962 (601.51kB), cpu: 373.33k, memory: 0B, network: 0B}/{rows: 25962 (601.51kB), cpu: 601.51k, memory: 0B, network: 0B}
           CPU: 5.00ms (38.46%), Scheduled: 8.00ms (42.11%), Blocked: 0.00ns (0.00%), Output: 25962 rows (351.63kB)
           Input avg.: 8654.00 rows, Input std.dev.: 60.66%
           expr_0 := double '0.95'
           latency_ms := 21:latency_ms:double
           agent_id := 5:agent_id:varchar
           20:event_date:date
               :: [[2026-10-09, <max>)]
           Input: 25962 rows (332.03kB), Filtered: 0.00%, Physical input: 2.31MB, Physical input time: 624.92us


```

### analyze_without_partition_filter

**EXPLAIN ANALYZE - full table scan (no partition filter)**

- **Question:** What does the same aggregation cost without a partition filter?
- **SQL concepts:** EXPLAIN ANALYZE baseline for pruning comparison
- **Interpretation:** Every partition is read; the difference to the filtered plan is the pruning benefit.
- **Parameters:** `days=0`

```sql
EXPLAIN ANALYZE
SELECT agent_id, count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95
FROM lakehouse.analytics.agent_run_metrics
GROUP BY agent_id
```

Sample output - 1 row(s) shown from export, elapsed 217 ms, processed rows 45980:

```text
Trino version: 467
Queued: 190.44us, Analysis: 13.26ms, Planning: 21.84ms, Execution: 193.10ms
Fragment 1 [HASH]
    CPU: 5.42ms, Scheduled: 6.86ms, Blocked 1.38s (Input: 689.58ms, Output: 0.00ns), Input: 28 rows (24.85kB); per task: avg.: 28.00 std.dev.: 0.00, Output: 4 rows (143B)
    Peak Memory: 1.29MB, Tasks count: 1; per task: max: 1.29MB
    Output layout: [agent_id, count, approx_percentile]
    Output partitioning: SINGLE []
    Aggregate[type = FINAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count:bigint, approx_percentile:double]
    │   Estimates: {rows: ? (?), cpu: 3.06M, memory: ?, network: 0B}
    │   CPU: 1.00ms (4.00%), Scheduled: 2.00ms (2.44%), Blocked: 0.00ns (0.00%), Output: 4 rows (143B)
    │   Input avg.: 1.75 rows, Input std.dev.: 300.00%
    │   count := count(count_1)
    │   approx_percentile := approx_percentile(approx_percentile_2)
    └─ LocalExchange[partitioning = HASH, arguments = [agent_id::varchar]]
       │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
       │   Estimates: {rows: 45980 (3.06MB), cpu: 3.06M, memory: 0B, network: 0B}
       │   CPU: 2.00ms (8.00%), Scheduled: 2.00ms (2.44%), Blocked: 690.00ms (50.00%), Output: 28 rows (24.85kB)
       │   Input avg.: 1.75 rows, Input std.dev.: 113.39%
       └─ RemoteSource[sourceFragmentIds = [2]]
              Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
              CPU: 0.00ns (0.00%), Scheduled: 0.00ns (0.00%), Blocked: 690.00ms (50.00%), Output: 28 rows (24.85kB)
              Input avg.: 1.75 rows, Input std.dev.: 113.39%

Fragment 2 [SOURCE]
    CPU: 23.15ms, Scheduled: 79.39ms, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 45980 rows (589.15kB); per task: avg.: 45980.00 std.dev.: 0.00, Output: 28 rows (24.85kB)
    Peak Memory: 4.74kB, Tasks count: 1; per task: max: 4.74kB
    Output layout: [agent_id, count_1, approx_percentile_2]
    Output partitioning: HASH [agent_id]
    Aggregate[type = PARTIAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
    │   Estimates: {rows: 45980 (3.06MB), cpu: ?, memory: ?, network: ?}
    │   CPU: 8.00ms (32.00%), Scheduled: 10.00ms (12.20%), Blocked: 0.00ns (0.00%), Output: 28 rows (24.85kB)
    │   Input avg.: 6568.57 rows, Input std.dev.: 62.58%
    │   count_1 := count(*)
    │   approx_percentile_2 := approx_percentile(latency_ms, expr_0)
    └─ ScanProject[table = lakehouse:analytics.agent_run_metrics$data@1920632619667562006]
           Layout: [latency_ms:double, expr_0:double, agent_id:varchar]
           Estimates: {rows: 45980 (1.04MB), cpu: 661.75k, memory: 0B, network: 0B}/{rows: 45980 (1.04MB), cpu: 1.04M, memory: 0B, network: 0B}
           CPU: 14.00ms (56.00%), Scheduled: 68.00ms (82.93%), Blocked: 0.00ns (0.00%), Output: 45980 rows (634.56kB)
           Input avg.: 6568.57 rows, Input std.dev.: 62.58%
           expr_0 := double '0.95'
           latency_ms := 21:latency_ms:double
           agent_id := 5:agent_id:varchar
           Input: 45980 rows (589.15kB), Filtered: 0.00%, Physical input: 4.15MB, Physical input time: 47.96ms


```

### analyze_column_projection

**EXPLAIN ANALYZE - columnar projection (2 columns of a wide table)**

- **Question:** How many bytes are read when a query touches 2 of the 22 columns of raw_agent_events?
- **SQL concepts:** Parquet columnar reads: only referenced columns are fetched
- **Interpretation:** raw_value (full JSON) dominates the table size; queries that do not reference it skip those column chunks entirely. Compare physical input bytes with exp_tier_raw_json, which must read raw_value.
- **Parameters:** `days=60`

```sql
EXPLAIN ANALYZE
SELECT event_type, count(*) AS events
FROM lakehouse.analytics.raw_agent_events
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY event_type
```

Sample output - 1 row(s) shown from export, elapsed 271 ms, processed rows 676374:

```text
Trino version: 467
Queued: 247.36us, Analysis: 19.53ms, Planning: 99.57ms, Execution: 239.60ms
Fragment 1 [HASH]
    CPU: 5.08ms, Scheduled: 6.02ms, Blocked 834.92ms (Input: 415.12ms, Output: 0.00ns), Input: 38 rows (1.05kB); per task: avg.: 38.00 std.dev.: 0.00, Output: 8 rows (216B)
    Peak Memory: 3.69MB, Tasks count: 1; per task: max: 3.69MB
    Output layout: [event_type, count]
    Output partitioning: SINGLE []
    Aggregate[type = FINAL, keys = [event_type]]
    │   Layout: [event_type:varchar, count:bigint]
    │   Estimates: {rows: ? (?), cpu: 9.04M, memory: ?, network: 0B}
    │   CPU: 1.00ms (4.76%), Scheduled: 1.00ms (2.04%), Blocked: 0.00ns (0.00%), Output: 8 rows (216B)
    │   Input avg.: 2.38 rows, Input std.dev.: 174.80%
    │   count := count(count_0)
    └─ LocalExchange[partitioning = HASH, arguments = [event_type::varchar]]
       │   Layout: [event_type:varchar, count_0:bigint]
       │   Estimates: {rows: 676374 (9.04MB), cpu: 9.04M, memory: 0B, network: 0B}
       │   CPU: 1.00ms (4.76%), Scheduled: 2.00ms (4.08%), Blocked: 420.00ms (50.30%), Output: 38 rows (1.05kB)
       │   Input avg.: 2.38 rows, Input std.dev.: 143.46%
       └─ RemoteSource[sourceFragmentIds = [2]]
              Layout: [event_type:varchar, count_0:bigint]
              CPU: 0.00ns (0.00%), Scheduled: 0.00ns (0.00%), Blocked: 415.00ms (49.70%), Output: 38 rows (1.05kB)
              Input avg.: 2.38 rows, Input std.dev.: 143.46%

Fragment 2 [SOURCE]
    CPU: 20.09ms, Scheduled: 46.86ms, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 676374 rows (2.59MB); per task: avg.: 676374.00 std.dev.: 0.00, Output: 38 rows (1.05kB)
    Peak Memory: 2.90kB, Tasks count: 1; per task: max: 2.90kB
    Output layout: [event_type, count_0]
    Output partitioning: HASH [event_type]
    Aggregate[type = PARTIAL, keys = [event_type]]
    │   Layout: [event_type:varchar, count_0:bigint]
    │   Estimates: {rows: 676374 (9.04MB), cpu: ?, memory: ?, network: ?}
    │   CPU: 5.00ms (23.81%), Scheduled: 5.00ms (10.20%), Blocked: 0.00ns (0.00%), Output: 38 rows (1.05kB)
    │   Input avg.: 96624.86 rows, Input std.dev.: 62.99%
    │   count_0 := count(*)
    └─ TableScan[table = lakehouse:analytics.raw_agent_events$data@2444391658245296219 constraint on [event_date]]
           Layout: [event_type:varchar]
           Estimates: {rows: 676374 (3.23MB), cpu: 3.23M, memory: 0B, network: 0B}
           CPU: 14.00ms (66.67%), Scheduled: 41.00ms (83.67%), Blocked: 0.00ns (0.00%), Output: 676374 rows (2.59MB)
           Input avg.: 96624.86 rows, Input std.dev.: 62.99%
           event_type := 2:event_type:varchar
           5:event_date:date
               :: [[2026-08-10, <max>)]
           Input: 676374 rows (2.59MB), Physical input: 339.55kB, Physical input time: 30.20ms


```

### exp_tier_raw_json

**Tier 1 - daily success rate from raw JSON (schema-on-read)**

- **Question:** Daily success rate per agent version, computed directly from raw Kafka payloads.
- **SQL concepts:** JSON functions over the bronze table; full-column reads of raw_value
- **Interpretation:** Must read and parse the large raw_value column for every run.metrics event (slowest tier).
- **Parameters:** `days=60`

```sql
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
ORDER BY event_date, agent_id, agent_version
```

Sample output - 32 row(s) shown from export, elapsed 691 ms, processed rows 676374:

| event_date | agent_id | agent_version | runs | success_rate |
|---|---|---|---|---|
| 2026-10-06 | ops-tool-agent | 1.0.0 | 316 | 0.9051 |
| 2026-10-06 | ops-tool-agent | 1.1.0 | 326 | 0.8926 |
| 2026-10-06 | planner-agent | 1.0.0 | 287 | 0.6237 |
| 2026-10-06 | planner-agent | 2.0.0 | 302 | 0.7185 |
| 2026-10-06 | qa-assistant | 1.0.0 | 306 | 0.8137 |
| 2026-10-06 | qa-assistant | 1.1.0 | 289 | 0.9031 |
| 2026-10-06 | rag-helpdesk | 2.0.0 | 274 | 0.8942 |
| 2026-10-06 | rag-helpdesk | 2.1.0 | 291 | 0.7835 |
| 2026-10-07 | ops-tool-agent | 1.0.0 | 837 | 0.8889 |
| 2026-10-07 | ops-tool-agent | 1.1.0 | 823 | 0.8591 |
| 2026-10-07 | planner-agent | 1.0.0 | 805 | 0.6248 |
| 2026-10-07 | planner-agent | 2.0.0 | 783 | 0.7625 |

_20 more rows not shown (full result in docs/sql_outputs)._

### exp_tier_curated

**Tier 2 - daily success rate from curated Iceberg facts**

- **Question:** Daily success rate per agent version from agent_run_metrics.
- **SQL concepts:** Typed columnar facts, partition pruning
- **Interpretation:** Reads two narrow typed columns (task_success, keys) instead of JSON text.
- **Parameters:** `days=60`

```sql
SELECT
    event_date,
    agent_id,
    agent_version,
    count(*) AS runs,
    round(avg(IF(task_success, 1e0, 0e0)), 4) AS success_rate
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY event_date, agent_id, agent_version
ORDER BY event_date, agent_id, agent_version
```

Sample output - 32 row(s) shown from export, elapsed 254 ms, processed rows 45980:

| event_date | agent_id | agent_version | runs | success_rate |
|---|---|---|---|---|
| 2026-10-06 | ops-tool-agent | 1.0.0 | 316 | 0.9051 |
| 2026-10-06 | ops-tool-agent | 1.1.0 | 326 | 0.8926 |
| 2026-10-06 | planner-agent | 1.0.0 | 287 | 0.6237 |
| 2026-10-06 | planner-agent | 2.0.0 | 302 | 0.7185 |
| 2026-10-06 | qa-assistant | 1.0.0 | 306 | 0.8137 |
| 2026-10-06 | qa-assistant | 1.1.0 | 289 | 0.9031 |
| 2026-10-06 | rag-helpdesk | 2.0.0 | 274 | 0.8942 |
| 2026-10-06 | rag-helpdesk | 2.1.0 | 291 | 0.7835 |
| 2026-10-07 | ops-tool-agent | 1.0.0 | 837 | 0.8889 |
| 2026-10-07 | ops-tool-agent | 1.1.0 | 823 | 0.8591 |
| 2026-10-07 | planner-agent | 1.0.0 | 805 | 0.6248 |
| 2026-10-07 | planner-agent | 2.0.0 | 783 | 0.7625 |

_20 more rows not shown (full result in docs/sql_outputs)._

### exp_tier_summary

**Tier 3 - daily success rate from the pre-aggregated summary table**

- **Question:** Daily success rate per agent version from daily_agent_summary.
- **SQL concepts:** Materialised aggregate (one row per day x agent version)
- **Interpretation:** Reads a handful of pre-aggregated rows; freshness depends on the last summary refresh.
- **Parameters:** `days=60`

```sql
SELECT
    event_date,
    agent_id,
    agent_version,
    runs,
    round(success_rate, 4) AS success_rate
FROM lakehouse.analytics.daily_agent_summary
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY event_date, agent_id, agent_version
```

Sample output - 32 row(s) shown from export, elapsed 71 ms, processed rows 32:

| event_date | agent_id | agent_version | runs | success_rate |
|---|---|---|---|---|
| 2026-10-06 | ops-tool-agent | 1.0.0 | 316 | 0.9051 |
| 2026-10-06 | ops-tool-agent | 1.1.0 | 326 | 0.8926 |
| 2026-10-06 | planner-agent | 1.0.0 | 287 | 0.6237 |
| 2026-10-06 | planner-agent | 2.0.0 | 302 | 0.7185 |
| 2026-10-06 | qa-assistant | 1.0.0 | 306 | 0.8137 |
| 2026-10-06 | qa-assistant | 1.1.0 | 289 | 0.9031 |
| 2026-10-06 | rag-helpdesk | 2.0.0 | 274 | 0.8942 |
| 2026-10-06 | rag-helpdesk | 2.1.0 | 291 | 0.7835 |
| 2026-10-07 | ops-tool-agent | 1.0.0 | 837 | 0.8889 |
| 2026-10-07 | ops-tool-agent | 1.1.0 | 823 | 0.8591 |
| 2026-10-07 | planner-agent | 1.0.0 | 805 | 0.6248 |
| 2026-10-07 | planner-agent | 2.0.0 | 783 | 0.7625 |

_20 more rows not shown (full result in docs/sql_outputs)._

### layout_lookup_unsorted

**Trace lookup on the streaming-written (unsorted) span table**

- **Question:** How many data files and rows must be read to fetch one trace from agent_spans?
- **SQL concepts:** File skipping via Parquet/Iceberg min-max statistics (or lack of it)
- **Interpretation:** Streaming micro-batches write files whose trace_id ranges overlap, so little can be skipped.
- **Parameters:** `trace_id='00000000000000000000000000000000'`

```sql
EXPLAIN ANALYZE
SELECT span_id, span_kind, duration_ms
FROM lakehouse.analytics.agent_spans
WHERE trace_id = :trace_id
```

Sample output - 1 row(s) shown from export, elapsed 204 ms, processed rows 0:

```text
Trino version: 467
Queued: 860.83us, Analysis: 23.57ms, Planning: 36.32ms, Execution: 175.63ms
Fragment 1 [SOURCE]
    CPU: 159.29us, Scheduled: 179.53us, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 0 rows (0B); per task: avg.: 0.00 std.dev.: 0.00, Output: 0 rows (0B)
    Peak Memory: 0B, Tasks count: 1; per task: max: 0B
    Output layout: [span_id, span_kind, duration_ms]
    Output partitioning: SINGLE []
    ScanFilterProject[table = lakehouse:analytics.agent_spans$data@8907210680098053594, filterPredicate = (trace_id = varchar '00000000000000000000000000000000')]
        Layout: [span_id:varchar, span_kind:varchar, duration_ms:double]
        Estimates: {rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}
        CPU: 0.00ns (?%), Scheduled: 0.00ns (?%), Blocked: 0.00ns (?%), Output: 0 rows (0B)
        Input avg.: 0.00 rows, Input std.dev.: ?%
        duration_ms := 16:duration_ms:double
        span_id := 5:span_id:varchar
        span_kind := 10:span_kind:varchar
        trace_id := 4:trace_id:varchar
        Input: 0 rows (0B), Filtered: ?%


```

### layout_lookup_sorted

**Trace lookup on the trace_id-sorted copy**

- **Question:** Does sorting by trace_id reduce the data read for the same lookup?
- **SQL concepts:** Sorted table layout (sorted_by) enabling file skipping
- **Interpretation:** Compare input rows / files with layout_lookup_unsorted. The trade-off: sorting costs write time and is a batch (maintenance) operation, not something the streaming writer does per micro-batch.
- **Parameters:** `trace_id='00000000000000000000000000000000'`

```sql
EXPLAIN ANALYZE
SELECT span_id, span_kind, duration_ms
FROM lakehouse.analytics.agent_spans_sorted_by_trace
WHERE trace_id = :trace_id
```

Sample output - 1 row(s) shown from export, elapsed 203 ms, processed rows 0:

```text
Trino version: 467
Queued: 213.49us, Analysis: 20.54ms, Planning: 26.82ms, Execution: 157.43ms
Fragment 1 [SOURCE]
    CPU: 50.44us, Scheduled: 56.18us, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 0 rows (0B); per task: avg.: 0.00 std.dev.: 0.00, Output: 0 rows (0B)
    Peak Memory: 0B, Tasks count: 1; per task: max: 0B
    Output layout: [span_id, span_kind, duration_ms]
    Output partitioning: SINGLE []
    ScanFilterProject[table = lakehouse:analytics.agent_spans_sorted_by_trace$data@3528856922146687623, filterPredicate = (trace_id = varchar '00000000000000000000000000000000')]
        Layout: [span_id:varchar, span_kind:varchar, duration_ms:double]
        Estimates: {rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}
        CPU: 0.00ns (?%), Scheduled: 0.00ns (?%), Blocked: 0.00ns (?%), Output: 0 rows (0B)
        Input avg.: 0.00 rows, Input std.dev.: ?%
        duration_ms := 16:duration_ms:double
        span_id := 5:span_id:varchar
        span_kind := 10:span_kind:varchar
        trace_id := 4:trace_id:varchar
        Input: 0 rows (0B), Filtered: ?%


```

### files_per_partition

**Iceberg data files per partition (small-files check)**

- **Question:** How many data files does each table/partition have, and how big are they?
- **SQL concepts:** Iceberg metadata tables ("$files") queried with SQL
- **Interpretation:** Frequent streaming commits create many small files; compaction (sql/09: optimize) rewrites them into fewer, larger files, which reduces per-file open/plan overhead for queries.
- **Parameters:** `none`

```sql
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
ORDER BY table_name, event_date
```

Sample output - 8 row(s) shown from export, elapsed 143 ms, processed rows 14:

| table_name | event_date | data_files | records | size_mb | avg_file_kb |
|---|---|---|---|---|---|
| agent_spans | 2026-10-06 | 1 | 15607 | 0.85 | 866.1 |
| agent_spans | 2026-10-07 | 1 | 43526 | 2.36 | 2414.9 |
| agent_spans | 2026-10-08 | 2 | 72064 | 3.91 | 2000.3 |
| agent_spans | 2026-10-09 | 3 | 171383 | 9.3 | 3173.2 |
| raw_agent_events | 2026-10-06 | 1 | 34881 | 3.42 | 3503.0 |
| raw_agent_events | 2026-10-07 | 1 | 97248 | 9.67 | 9905.2 |
| raw_agent_events | 2026-10-08 | 2 | 160660 | 15.98 | 8182.3 |
| raw_agent_events | 2026-10-09 | 3 | 383585 | 37.84 | 12915.2 |

### storage_footprint

**Lakehouse storage footprint per table (Parquet/ZSTD on MinIO)**

- **Question:** How much object storage does each table use, and how many bytes per row?
- **SQL concepts:** Iceberg metadata ($files) aggregation; compression ratio estimate
- **Interpretation:** Sizes are compressed Parquet bytes reported by Iceberg metadata (actual files on MinIO).
- **Parameters:** `none`

```sql
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
ORDER BY size_mb DESC
```

Sample output - 6 row(s) shown from export, elapsed 198 ms, processed rows 39:

| table_name | files | records | size_mb | bytes_per_row |
|---|---|---|---|---|
| raw_agent_events | 7 | 676374 | 66.91 | 103.7 |
| agent_spans | 7 | 302580 | 16.41 | 56.9 |
| agent_evaluation_results | 7 | 324686 | 11.79 | 38.1 |
| agent_run_metrics | 7 | 45980 | 4.15 | 94.7 |
| agent_security_findings | 7 | 2674 | 0.22 | 87.2 |
| daily_agent_summary | 4 | 32 | 0.01 | 447.4 |


## 09_lakehouse_features.sql

### snapshot_history

**Snapshot history of a streaming-written table**

- **Question:** How many commits has the stream made to agent_run_metrics, and what did each add?
- **SQL concepts:** Iceberg "$snapshots" metadata table; every Spark micro-batch commit is a snapshot
- **Interpretation:** The summary map holds Iceberg commit stats plus our agentshield.batch_id property, which the stream uses to skip already-committed tables when a micro-batch is replayed after a crash.
- **Parameters:** `none`

```sql
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
LIMIT 15
```

Sample output - 4 row(s) shown from export, elapsed 108 ms, processed rows 4:

| committed_at | snapshot_id | operation | added_records | total_records | added_files | stream_batch_id |
|---|---|---|---|---|---|---|
| 2026-10-09T15:24:30.005000+00:00 | 1920632619667562006 | append | 5658 | 45980 | 1 | 3 |
| 2026-10-09T15:24:16.010000+00:00 | 1488821045953757403 | append | 20342 | 40322 | 2 | 2 |
| 2026-10-09T15:23:55.635000+00:00 | 7016487036279333152 | append | 19980 | 19980 | 4 | 1 |
| 2026-10-09T15:22:53.029000+00:00 | 400282557845404738 | append | NULL | 0 | NULL | NULL |

### time_travel_row_counts

**Time travel - current table vs the table as of one minute ago**

- **Question:** How many runs did agent_run_metrics hold one minute ago compared with now?
- **SQL concepts:** FOR TIMESTAMP AS OF (Iceberg time travel; requires a constant expression)
- **Interpretation:** Each snapshot is an immutable table version, so historical reports are reproducible. Snapshot-id time travel (FOR VERSION AS OF <id>) and rollback are demonstrated by benchmarks/lakehouse_features_demo.py.
- **Parameters:** `none`

```sql
SELECT 'current' AS version, count(*) AS runs FROM lakehouse.analytics.agent_run_metrics
UNION ALL
SELECT 'as of 1 minute ago', count(*)
FROM lakehouse.analytics.agent_run_metrics FOR TIMESTAMP AS OF (current_timestamp - INTERVAL '1' MINUTE)
```

Sample output - 2 row(s) shown from export, elapsed 96 ms, processed rows 45980:

| version | runs |
|---|---|
| as of 1 minute ago | 0 |
| current | 45980 |

### schema_evolution_result

**Schema evolution - old rows read the added column as NULL**

- **Question:** After adding routing_strategy, what do old and new rows contain?
- **SQL concepts:** ALTER TABLE ADD COLUMN on Iceberg (metadata-only change)
- **Interpretation:** Iceberg tracks columns by ID, so adding a column is a metadata operation; no file rewrite.
- **Parameters:** `none`

```sql
SELECT coalesce(routing_strategy, '<NULL: written before ADD COLUMN>') AS routing_strategy, count(*) AS rows_
FROM lakehouse.analytics.demo_evolution
GROUP BY 1
```

Sample output - 2 row(s) shown from export, elapsed 132 ms, processed rows 1200:

| routing_strategy | rows_ |
|---|---|
| <NULL: written before ADD COLUMN> | 1000 |
| cost_aware | 200 |

### rollback_candidates

**Snapshots of the scratch table (rollback targets)**

- **Question:** Which snapshot would restore the scratch table to before the last INSERT?
- **SQL concepts:** Iceberg snapshot lineage; rollback with CALL system.rollback_to_snapshot
- **Interpretation:** To roll back (scratch table only): CALL lakehouse.system.rollback_to_snapshot('analytics', 'demo_evolution', <parent snapshot_id>) benchmarks/lakehouse_features_demo.py performs and verifies this rollback.
- **Parameters:** `none`

```sql
SELECT committed_at, snapshot_id, parent_id, operation, element_at(summary, 'added-records') AS added_records,
       element_at(summary, 'total-records') AS total_records
FROM lakehouse.analytics."demo_evolution$snapshots"
ORDER BY committed_at
```

Sample output - 2 row(s) shown from export, elapsed 58 ms, processed rows 2:

| committed_at | snapshot_id | parent_id | operation | added_records | total_records |
|---|---|---|---|---|---|
| 2026-10-09T15:24:51.676000+00:00 | 6952394289294953375 | NULL | append | 1000 | 1000 |
| 2026-10-09T15:24:52.059000+00:00 | 7689789007103398000 | 6952394289294953375 | append | 200 | 1200 |

### partitions_overview

**Partition statistics of the span fact table**

- **Question:** How are rows and files distributed across event_date partitions?
- **SQL concepts:** Iceberg "$partitions" metadata table
- **Interpretation:** Balanced, date-aligned partitions keep pruning effective; many tiny files per partition signal that compaction is due.
- **Parameters:** `none`

```sql
SELECT "partition".event_date AS event_date, record_count, file_count,
       round(total_size / 1048576e0, 2) AS size_mb
FROM lakehouse.analytics."agent_spans$partitions"
ORDER BY event_date
```

Sample output - 4 row(s) shown from export, elapsed 96 ms, processed rows 4:

| event_date | record_count | file_count | size_mb |
|---|---|---|---|
| 2026-10-06 | 15607 | 1 | 0.85 |
| 2026-10-07 | 43526 | 1 | 2.36 |
| 2026-10-08 | 72064 | 2 | 3.91 |
| 2026-10-09 | 171383 | 3 | 9.3 |
