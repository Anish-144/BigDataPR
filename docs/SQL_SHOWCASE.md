# SQL showcase

Every query below is in the `sql/` directory, runs on Trino over Iceberg/Parquet, and is also served by the API's read-only query gallery. Sample outputs are **real results** exported from the current dataset with `python -m lakehouse.run_sql "sql/0[2-9]*.sql" --export docs/sql_outputs`; elapsed times are single-node Trino wall times. Parameters (`:days`, ...) are bound as prepared-statement parameters.

Notes for readers: `1e0` literals are DOUBLE on purpose - `1.0` is DECIMAL(2,1) in Trino and `avg()` over it silently rounds rates to one decimal place. `approx_percentile` is approximate (see exact_vs_approx_p95).

## Contents

- `02_performance_analytics.sql`: [latency_percentiles_by_version](#latency-percentiles-by-version), [exact_vs_approx_p95](#exact-vs-approx-p95), [hourly_throughput](#hourly-throughput), [tool_performance](#tool-performance), [error_categories](#error-categories), [token_and_cost_summary](#token-and-cost-summary), [streaming_batch_stats](#streaming-batch-stats), [worker_resource_usage](#worker-resource-usage)
- `03_window_functions_and_rankings.sql`: [rank_p95_within_model](#rank-p95-within-model), [top_expensive_agents](#top-expensive-agents), [top_failures_per_agent](#top-failures-per-agent), [rolling_success_rate](#rolling-success-rate), [highest_risk_scenarios](#highest-risk-scenarios), [cumulative_events_per_test_run](#cumulative-events-per-test-run)
- `04_regression_comparison.sql`: [version_regression_lag](#version-regression-lag), [cohort_ab_comparison](#cohort-ab-comparison), [retrieval_quality_by_version](#retrieval-quality-by-version), [quality_metrics_by_version](#quality-metrics-by-version), [cost_per_successful_task](#cost-per-successful-task), [prompt_model_comparison](#prompt-model-comparison)
- `05_security_correlation.sql`: [findings_by_rule_and_severity](#findings-by-rule-and-severity), [findings_with_trace_evidence](#findings-with-trace-evidence), [anomaly_security_correlation](#anomaly-security-correlation), [window_correlation_perf_errors_security](#window-correlation-perf-errors-security), [exfiltration_sequences](#exfiltration-sequences), [security_detection_vs_ground_truth](#security-detection-vs-ground-truth), [security_residuals_vs_quarantine](#security-residuals-vs-quarantine)
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

Sample output - 8 row(s) shown from export, elapsed 1204 ms, processed rows 609878:

| agent_name | agent_version | model_name | runs | avg_ms | p50_ms | p90_ms | p95_ms | p99_ms | p50_ttft_ms | avg_tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| Planner Agent | 2.0.0 | mock-large | 76200 | 4309.4 | 4113.0 | 5748.6 | 6365.2 | 10094.0 | 3076.9 | 3472.2 |
| Planner Agent | 1.0.0 | mock-large | 75746 | 3787.3 | 3516.4 | 5043.3 | 5714.0 | 9464.3 | 2378.4 | 2551.2 |
| RAG Helpdesk | 2.0.0 | mock-medium | 76146 | 1647.9 | 1471.3 | 2161.2 | 2487.8 | 3832.4 | 722.5 | 1914.7 |
| RAG Helpdesk | 2.1.0 | mock-medium | 76869 | 1446.8 | 1279.1 | 1873.8 | 2157.3 | 3455.0 | 628.3 | 1412.1 |
| Ops Tool Agent | 1.1.0 | mock-small | 76396 | 1543.3 | 1377.1 | 1886.0 | 2120.1 | 4125.6 | 891.3 | 1006.3 |
| Ops Tool Agent | 1.0.0 | mock-small | 75572 | 1373.2 | 1208.4 | 1598.5 | 1792.3 | 3857.0 | 789.3 | 785.4 |
| QA Assistant | 1.1.0 | mock-medium | 76493 | 970.2 | 910.1 | 1378.4 | 1563.8 | 2072.1 | 183.1 | 616.6 |
| QA Assistant | 1.0.0 | mock-small | 76456 | 707.4 | 651.0 | 1041.6 | 1212.6 | 1656.8 | 143.3 | 508.4 |

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

Sample output - 8 row(s) shown from export, elapsed 1915 ms, processed rows 1219756:

| agent_name | agent_version | runs | exact_p95_ms | approx_p95_ms | approx_error_pct |
|---|---|---|---|---|---|
| Planner Agent | 2.0.0 | 76200 | 6359.5 | 6354.5 | -0.079 |
| RAG Helpdesk | 2.0.0 | 76146 | 2492.6 | 2496.4 | 0.152 |
| Ops Tool Agent | 1.0.0 | 75572 | 1785.7 | 1789.1 | 0.189 |
| RAG Helpdesk | 2.1.0 | 76869 | 2156.3 | 2158.9 | 0.123 |
| Ops Tool Agent | 1.1.0 | 76396 | 2116.4 | 2118.3 | 0.092 |
| QA Assistant | 1.0.0 | 76456 | 1212.6 | 1214.5 | 0.154 |
| QA Assistant | 1.1.0 | 76493 | 1563.3 | 1563.7 | 0.024 |
| Planner Agent | 1.0.0 | 75746 | 5708.6 | 5708.8 | 0.004 |

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

Sample output - 181 row(s) shown from export, elapsed 6538 ms, processed rows 10180697:

| event_hour | events | runs | spans | avg_events_per_sec | success_rate |
|---|---|---|---|---|---|
| 2026-10-02T19:00:00+00:00 | 4565 | 307 | 2068 | 1.27 | 0.8339 |
| 2026-10-02T20:00:00+00:00 | 5997 | 410 | 2684 | 1.67 | 0.8122 |
| 2026-10-02T21:00:00+00:00 | 5920 | 411 | 2676 | 1.64 | 0.8029 |
| 2026-10-02T22:00:00+00:00 | 5821 | 409 | 2605 | 1.62 | 0.8337 |
| 2026-10-02T23:00:00+00:00 | 5980 | 409 | 2688 | 1.66 | 0.8044 |
| 2026-10-03T00:00:00+00:00 | 6118 | 410 | 2756 | 1.7 | 0.839 |
| 2026-10-03T01:00:00+00:00 | 6070 | 411 | 2732 | 1.69 | 0.8078 |
| 2026-10-03T02:00:00+00:00 | 6066 | 409 | 2684 | 1.69 | 0.8044 |
| 2026-10-03T03:00:00+00:00 | 6027 | 410 | 2687 | 1.67 | 0.7878 |
| 2026-10-03T04:00:00+00:00 | 6049 | 409 | 2725 | 1.68 | 0.7873 |
| 2026-10-03T05:00:00+00:00 | 5829 | 410 | 2602 | 1.62 | 0.8171 |
| 2026-10-03T06:00:00+00:00 | 7715 | 509 | 3462 | 2.14 | 0.8016 |

_169 more rows not shown (full result in docs/sql_outputs)._

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

Sample output - 13 row(s) shown from export, elapsed 965 ms, processed rows 3999817:

| tool_name | calls | retries | timeouts | tool_errors | invalid_args | policy_denied | non_ok_pct | avg_ms | p95_ms |
|---|---|---|---|---|---|---|---|---|---|
| document_lookup | 261276 | 5064 | 1679 | 3646 | 3455 | 2 | 3.36 | 197.8 | 255.4 |
| search_kb | 142234 | 6365 | 981 | 5571 | 0 | 105 | 4.68 | 224.8 | 283.0 |
| calculator | 109595 | 11358 | 666 | 14180 | 0 | 326 | 13.84 | 213.8 | 276.8 |
| get_order_status | 108996 | 5165 | 1175 | 4225 | 3431 | 335 | 8.41 | 253.2 | 283.6 |
| create_ticket | 102183 | 4222 | 360 | 3913 | 3420 | 252 | 7.78 | 190.2 | 274.5 |
| delegate_subtask | 60030 | 2694 | 752 | 2081 | 0 | 0 | 4.72 | 270.7 | 283.9 |
| export_data | 1218 | 0 | 0 | 0 | 0 | 1218 | 100.0 | NULL | NULL |
| send_external_email | 991 | 0 | 0 | 0 | 0 | 991 | 100.0 | NULL | NULL |
| http_post | 951 | 0 | 0 | 0 | 0 | 951 | 100.0 | NULL | NULL |
| read_resource | 787 | 0 | 0 | 0 | 0 | 787 | 100.0 | NULL | NULL |
| modify_permissions | 638 | 0 | 0 | 0 | 0 | 638 | 100.0 | NULL | NULL |
| delete_records | 427 | 0 | 0 | 0 | 0 | 427 | 100.0 | NULL | NULL |

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

Sample output - 8 row(s) shown from export, elapsed 417 ms, processed rows 609878:

| agent_name | agent_version | runs | completed | failed | timed_out | unsuccessful_tasks | err_tool_timeout | err_tool_error | err_malformed | err_retrieval | err_loop_budget | error_rate_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Planner Agent | 1.0.0 | 75746 | 72564 | 3035 | 147 | 28210 | 147 | 950 | 798 | 1 | 0 | 4.2 |
| Ops Tool Agent | 1.1.0 | 76396 | 73205 | 3025 | 166 | 10702 | 166 | 1097 | 1106 | 0 | 246 | 4.18 |
| Planner Agent | 2.0.0 | 76200 | 73821 | 2334 | 45 | 19728 | 45 | 693 | 671 | 10 | 0 | 3.12 |
| Ops Tool Agent | 1.0.0 | 75572 | 73521 | 1879 | 172 | 6536 | 172 | 673 | 595 | 0 | 290 | 2.71 |
| QA Assistant | 1.0.0 | 76456 | 75488 | 968 | 0 | 13651 | 0 | 0 | 968 | 0 | 0 | 1.27 |
| RAG Helpdesk | 2.0.0 | 76146 | 75261 | 885 | 0 | 9316 | 0 | 0 | 630 | 255 | 0 | 1.16 |
| RAG Helpdesk | 2.1.0 | 76869 | 76013 | 856 | 0 | 14767 | 0 | 0 | 636 | 220 | 0 | 1.11 |
| QA Assistant | 1.1.0 | 76493 | 76081 | 412 | 0 | 6149 | 0 | 0 | 412 | 0 | 0 | 0.54 |

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

Sample output - 8 row(s) shown from export, elapsed 676 ms, processed rows 609878:

| model_name | agent_name | agent_version | runs | input_tokens | output_tokens | avg_tokens_per_run | est_total_cost_usd | est_cost_per_1k_runs_usd | runs_without_pricing | cost_source |
|---|---|---|---|---|---|---|---|---|---|---|
| mock-large | Planner Agent | 2.0.0 | 76200 | 222329996 | 42254666 | 3472.2 | 978.3717 | 12.8395 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-large | Planner Agent | 1.0.0 | 75746 | 159803818 | 33439075 | 2551.2 | 733.9003 | 9.689 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-medium | RAG Helpdesk | 2.0.0 | 76146 | 127353554 | 18442921 | 1914.7 | 160.9002 | 2.113 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-medium | RAG Helpdesk | 2.1.0 | 76869 | 91535781 | 17009129 | 1412.1 | 127.6578 | 1.6607 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-medium | QA Assistant | 1.1.0 | 76493 | 35992618 | 11175223 | 616.6 | 64.5548 | 0.8439 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-small | Ops Tool Agent | 1.1.0 | 76396 | 61451263 | 15428100 | 1006.3 | 18.4745 | 0.2418 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-small | Ops Tool Agent | 1.0.0 | 75572 | 48230244 | 11121405 | 785.4 | 13.9074 | 0.184 | 0 | local_pricing_config:local-demo-2026.10 |
| mock-small | QA Assistant | 1.0.0 | 76456 | 29986969 | 8884849 | 508.4 | 9.829 | 0.1286 | 0 | local_pricing_config:local-demo-2026.10 |

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

Sample output - 1 row(s) shown from export, elapsed 152 ms, processed rows 36:

| query_name | batches | rows_in | rows_invalid | avg_batch_ms | p95_batch_ms | rows_per_sec_while_busy | peak_batch_rows_per_sec | avg_ingest_lag_ms | max_ingest_lag_ms |
|---|---|---|---|---|---|---|---|---|---|
| lakehouse_fanout | 36 | 8961181 | 11735 | 20329.0 | 42701.0 | 12244.8 | 21928.3 | 4731560.0 | 41779912.0 |

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

Sample output - 5 row(s) shown from export, elapsed 218 ms, processed rows 240:

| test_run_id | test_run_name | workers | samples | avg_cpu_pct | peak_memory_mb | avg_events_per_sec_per_worker |
|---|---|---|---|---|---|---|
| TR-20261010-69ab72 | benchmark_5000000 | 6 | 162 | 104.7 | 78.6 | 6091.4 |
| TR-20261009-34bcb1 | benchmark_1000000 | 6 | 18 | 105.9 | 76.8 | 9430.3 |
| TR-20261010-2fa7eb | benchmark_1000000 | 6 | 18 | 102.3 | 78.2 | 8633.2 |
| TR-20261010-e9b86d | benchmark_1000000 | 6 | 18 | 105.3 | 77.2 | 8865.0 |
| TR-20261009-83cb19 | baseline | 4 | 4 | 108.9 | 52.0 | 10056.9 |


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

Sample output - 8 row(s) shown from export, elapsed 229 ms, processed rows 609878:

| model_name | agent_name | agent_version | runs | p95_ms | p95_rank_in_model | cost_rank_overall | p95_percentile_rank |
|---|---|---|---|---|---|---|---|
| mock-large | Planner Agent | 2.0.0 | 76200 | 6362.3 | 1 | 1 | 1.0 |
| mock-large | Planner Agent | 1.0.0 | 75746 | 5717.8 | 2 | 2 | 0.857 |
| mock-medium | RAG Helpdesk | 2.0.0 | 76146 | 2490.7 | 1 | 3 | 0.714 |
| mock-medium | RAG Helpdesk | 2.1.0 | 76869 | 2156.6 | 2 | 4 | 0.571 |
| mock-medium | QA Assistant | 1.1.0 | 76493 | 1565.0 | 3 | 5 | 0.143 |
| mock-small | Ops Tool Agent | 1.1.0 | 76396 | 2116.3 | 1 | 6 | 0.429 |
| mock-small | Ops Tool Agent | 1.0.0 | 75572 | 1786.1 | 2 | 7 | 0.286 |
| mock-small | QA Assistant | 1.0.0 | 76456 | 1211.4 | 3 | 8 | 0.0 |

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

Sample output - 5 row(s) shown from export, elapsed 287 ms, processed rows 609878:

| agent_name | agent_version | model_name | runs | est_cost_usd | share_pct | cumulative_share_pct |
|---|---|---|---|---|---|---|
| Planner Agent | 2.0.0 | mock-large | 76200 | 978.3717 | 46.42 | 46.42 |
| Planner Agent | 1.0.0 | mock-large | 75746 | 733.9003 | 34.82 | 81.24 |
| RAG Helpdesk | 2.0.0 | mock-medium | 76146 | 160.9002 | 7.63 | 88.88 |
| RAG Helpdesk | 2.1.0 | mock-medium | 76869 | 127.6578 | 6.06 | 94.93 |
| QA Assistant | 1.1.0 | mock-medium | 76493 | 64.5548 | 3.06 | 98.0 |

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

Sample output - 11 row(s) shown from export, elapsed 343 ms, processed rows 609878:

| agent_name | rank | reason | n |
|---|---|---|---|
| Ops Tool Agent | 1 | wrong_answer | 11996 |
| Ops Tool Agent | 2 | tool_error | 1770 |
| Ops Tool Agent | 3 | malformed_response | 1701 |
| Planner Agent | 1 | wrong_answer | 42377 |
| Planner Agent | 2 | invalid_tool_args | 2246 |
| Planner Agent | 3 | tool_error | 1643 |
| QA Assistant | 1 | wrong_answer | 18420 |
| QA Assistant | 2 | malformed_response | 1380 |
| RAG Helpdesk | 1 | wrong_answer | 22342 |
| RAG Helpdesk | 2 | malformed_response | 1266 |
| RAG Helpdesk | 3 | retrieval_error | 475 |

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

Sample output - 200 row(s) shown from export, elapsed 264 ms, processed rows 609874:

| agent_id | agent_version | hour | runs | success_rate | moving_avg_6h | delta_vs_prev_hour |
|---|---|---|---|---|---|---|
| ops-tool-agent | 1.0.0 | 2026-10-02T19:00:00+00:00 | 36 | 0.9167 | 0.9167 | NULL |
| ops-tool-agent | 1.0.0 | 2026-10-02T20:00:00+00:00 | 45 | 0.8889 | 0.9028 | -0.0278 |
| ops-tool-agent | 1.0.0 | 2026-10-02T21:00:00+00:00 | 46 | 0.8913 | 0.899 | 0.0024 |
| ops-tool-agent | 1.0.0 | 2026-10-02T22:00:00+00:00 | 59 | 0.9492 | 0.9115 | 0.0578 |
| ops-tool-agent | 1.0.0 | 2026-10-02T23:00:00+00:00 | 45 | 0.9556 | 0.9203 | 0.0064 |
| ops-tool-agent | 1.0.0 | 2026-10-03T00:00:00+00:00 | 50 | 0.98 | 0.9303 | 0.0244 |
| ops-tool-agent | 1.0.0 | 2026-10-03T01:00:00+00:00 | 38 | 0.9474 | 0.9354 | -0.0326 |
| ops-tool-agent | 1.0.0 | 2026-10-03T02:00:00+00:00 | 48 | 0.9167 | 0.94 | -0.0307 |
| ops-tool-agent | 1.0.0 | 2026-10-03T03:00:00+00:00 | 49 | 0.9388 | 0.9479 | 0.0221 |
| ops-tool-agent | 1.0.0 | 2026-10-03T04:00:00+00:00 | 49 | 0.9184 | 0.9428 | -0.0204 |
| ops-tool-agent | 1.0.0 | 2026-10-03T05:00:00+00:00 | 41 | 0.9268 | 0.938 | 0.0085 |
| ops-tool-agent | 1.0.0 | 2026-10-03T06:00:00+00:00 | 71 | 0.9577 | 0.9343 | 0.0309 |

_188 more rows not shown (full result in docs/sql_outputs)._

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

Sample output - 15 row(s) shown from export, elapsed 360 ms, processed rows 632378:

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
| benchmark_5000000 | RAG Helpdesk | 2.0.0 | 43063 | 4179 | 470 | 97.04 | 1 |
| benchmark_1000000 | RAG Helpdesk | 2.0.0 | 25809 | 2490 | 291 | 96.48 | 1 |
| baseline | RAG Helpdesk | 2.0.0 | 2490 | 209 | 24 | 83.94 | 1 |
| regression | RAG Helpdesk | 2.0.0 | 1023 | 72 | 0 | 70.38 | 1 |

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

Sample output - 200 row(s) shown from export, elapsed 824 ms, processed rows 8960941:

| test_run_id | hour | events | cumulative_events |
|---|---|---|---|
| TR-20261009-34bcb1 | 2026-10-02T19:00:00+00:00 | 4565 | 4565 |
| TR-20261009-34bcb1 | 2026-10-02T20:00:00+00:00 | 5997 | 10562 |
| TR-20261009-34bcb1 | 2026-10-02T21:00:00+00:00 | 5920 | 16482 |
| TR-20261009-34bcb1 | 2026-10-02T22:00:00+00:00 | 5821 | 22303 |
| TR-20261009-34bcb1 | 2026-10-02T23:00:00+00:00 | 5980 | 28283 |
| TR-20261009-34bcb1 | 2026-10-03T00:00:00+00:00 | 6118 | 34401 |
| TR-20261009-34bcb1 | 2026-10-03T01:00:00+00:00 | 6070 | 40471 |
| TR-20261009-34bcb1 | 2026-10-03T02:00:00+00:00 | 6066 | 46537 |
| TR-20261009-34bcb1 | 2026-10-03T03:00:00+00:00 | 6027 | 52564 |
| TR-20261009-34bcb1 | 2026-10-03T04:00:00+00:00 | 6049 | 58613 |
| TR-20261009-34bcb1 | 2026-10-03T05:00:00+00:00 | 5829 | 64442 |
| TR-20261009-34bcb1 | 2026-10-03T06:00:00+00:00 | 6166 | 70608 |

_188 more rows not shown (full result in docs/sql_outputs)._


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

Sample output - 8 row(s) shown from export, elapsed 425 ms, processed rows 609878:

| agent_name | previous_version | agent_version | runs | avg_latency_ms | previous_version_latency | latency_change_pct | p95_latency_ms | success_rate | avg_tokens | success_rank |
|---|---|---|---|---|---|---|---|---|---|---|
| QA Assistant | 1.0.0 | 1.1.0 | 76493 | 970.2 | 707.4 | 37.15 | 1563.8 | 0.9196 | 616.6 | 1 |
| Planner Agent | 1.0.0 | 2.0.0 | 76200 | 4309.4 | 3787.3 | 13.79 | 6359.1 | 0.7411 | 3472.2 | 1 |
| Ops Tool Agent | 1.0.0 | 1.1.0 | 76396 | 1543.3 | 1373.2 | 12.39 | 2120.4 | 0.8599 | 1006.3 | 2 |
| RAG Helpdesk | 2.0.0 | 2.1.0 | 76869 | 1446.8 | 1647.9 | -12.2 | 2155.7 | 0.8079 | 1412.1 | 2 |
| Ops Tool Agent | NULL | 1.0.0 | 75572 | 1373.2 | NULL | NULL | 1789.7 | 0.9135 | 785.4 | 1 |
| RAG Helpdesk | NULL | 2.0.0 | 76146 | 1647.9 | NULL | NULL | 2493.8 | 0.8777 | 1914.7 | 1 |
| QA Assistant | NULL | 1.0.0 | 76456 | 707.4 | NULL | NULL | 1213.6 | 0.8215 | 508.4 | 2 |
| Planner Agent | NULL | 1.0.0 | 75746 | 3787.3 | NULL | NULL | 5712.7 | 0.6276 | 2551.2 | 2 |

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

Sample output - 4 row(s) shown from export, elapsed 429 ms, processed rows 663043:

| agent_name | baseline_version | candidate_version | baseline_runs | candidate_runs | base_success | cand_success | delta_success_pp | base_p95_ms | cand_p95_ms | delta_p95_pct | delta_tokens_pct | base_est_cost_per_success | cand_est_cost_per_success | delta_cost_per_success_pct | base_findings_per_1k | cand_findings_per_1k |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ops Tool Agent | 1.0.0 | 1.1.0 | 988 | 936 | 0.9119 | 0.8654 | -4.66 | 1761.9 | 2026.6 | 15.03 | 28.7 | 0.0002 | 0.0003 | 38.98 | 0.0 | 0.0 |
| Planner Agent | 1.0.0 | 2.0.0 | 1042 | 1013 | 0.6296 | 0.7345 | 10.49 | 5448.4 | 6036.9 | 10.8 | 36.47 | 0.0149 | 0.0171 | 14.23 | 0.0 | 0.0 |
| QA Assistant | 1.0.0 | 1.1.0 | 996 | 994 | 0.8283 | 0.9205 | 9.22 | 1232.4 | 1542.6 | 25.17 | 20.21 | 0.0002 | 0.0009 | 486.0 | 0.0 | 0.0 |
| RAG Helpdesk | 2.0.0 | 2.1.0 | 1023 | 1008 | 0.8876 | 0.8135 | -7.41 | 2409.6 | 2013.8 | -16.42 | -26.65 | 0.0023 | 0.002 | -14.44 | 70.38 | 44.64 |

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

Sample output - 4 row(s) shown from export, elapsed 3574 ms, processed rows 5532768:

| agent_name | agent_version | evaluated_runs | recall_at_k | precision_at_k | mrr | citation_coverage | groundedness | task_success_rate |
|---|---|---|---|---|---|---|---|---|
| Planner Agent | 1.0.0 | 50520 | 0.9938 | 0.2485 | 0.9905 | 0.9938 | 0.2975 | 0.5785 |
| Planner Agent | 2.0.0 | 50769 | 0.9982 | 0.2496 | 0.9967 | 0.9982 | 0.3434 | 0.6997 |
| RAG Helpdesk | 2.0.0 | 76129 | 0.9925 | 0.1985 | 0.9069 | 0.9593 | 0.7856 | 0.8777 |
| RAG Helpdesk | 2.1.0 | 76848 | 0.8997 | 0.2999 | 0.8055 | 0.8393 | 0.7232 | 0.8079 |

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

Sample output - 8 row(s) shown from export, elapsed 1032 ms, processed rows 4313012:

| agent_id | agent_version | runs | schema_validity | exact_match | token_f1 | tool_selection_acc | tool_argument_acc | hallucination_flag_rate |
|---|---|---|---|---|---|---|---|---|
| ops-tool-agent | 1.0.0 | 75632 | 0.9921 | 0.9135 | 0.9127 | 0.9599 | 0.9387 | 0.0269 |
| ops-tool-agent | 1.1.0 | 76536 | 0.9851 | 0.8599 | 0.8591 | 0.9382 | 0.9052 | 0.0433 |
| planner-agent | 1.0.0 | 75803 | 0.9891 | 0.6597 | 0.6621 | 0.9464 | 0.9245 | 0.1129 |
| planner-agent | 2.0.0 | 76333 | 0.9909 | 0.7629 | 0.7642 | 0.9677 | 0.9512 | 0.0798 |
| qa-assistant | 1.0.0 | 76495 | 0.9873 | 0.8214 | 0.8822 | NULL | NULL | 0.0563 |
| qa-assistant | 1.1.0 | 76623 | 0.9947 | 0.9196 | 0.9454 | NULL | NULL | 0.0251 |
| rag-helpdesk | 2.0.0 | 76194 | 0.9917 | 0.8778 | 0.9177 | NULL | NULL | 0.039 |
| rag-helpdesk | 2.1.0 | 77002 | 0.9917 | 0.8083 | 0.8864 | NULL | NULL | 0.062 |

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

Sample output - 8 row(s) shown from export, elapsed 341 ms, processed rows 609878:

| agent_name | agent_version | total_estimated_cost_usd | successful_tasks | estimated_cost_per_request | estimated_cost_per_success | tokens_per_success |
|---|---|---|---|---|---|---|
| QA Assistant | 1.0.0 | 9.829 | 62805 | 0.0001 | 0.0002 | 618.9 |
| Ops Tool Agent | 1.0.0 | 13.9074 | 69036 | 0.0002 | 0.0002 | 859.7 |
| Ops Tool Agent | 1.1.0 | 18.4745 | 65694 | 0.0002 | 0.0003 | 1170.3 |
| QA Assistant | 1.1.0 | 64.5548 | 70344 | 0.0008 | 0.0009 | 670.5 |
| RAG Helpdesk | 2.1.0 | 127.6578 | 62102 | 0.0017 | 0.0021 | 1747.8 |
| RAG Helpdesk | 2.0.0 | 160.9002 | 66830 | 0.0021 | 0.0024 | 2181.6 |
| Planner Agent | 1.0.0 | 733.9003 | 47536 | 0.0097 | 0.0154 | 4065.2 |
| Planner Agent | 2.0.0 | 978.3717 | 56472 | 0.0128 | 0.0173 | 4685.2 |

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

Sample output - 8 row(s) shown from export, elapsed 674 ms, processed rows 609894:

| prompt_version | model_name | released_at | runs | success_rate | p50_ms | avg_tokens | avg_retries |
|---|---|---|---|---|---|---|---|
| qa-p1 | mock-small | 2026-08-03 | 76456 | 0.8215 | 650.5 | 508.4 | 0.035 |
| rag-p3 | mock-medium | 2026-08-10 | 76146 | 0.8777 | 1471.6 | 1914.7 | 0.032 |
| ops-p1 | mock-small | 2026-08-17 | 75572 | 0.9135 | 1208.5 | 785.4 | 0.099 |
| plan-p1 | mock-large | 2026-08-24 | 75746 | 0.6276 | 3509.1 | 2551.2 | 0.221 |
| qa-p2 | mock-medium | 2026-09-14 | 76493 | 0.9196 | 910.2 | 616.6 | 0.014 |
| rag-p4 | mock-medium | 2026-09-21 | 76869 | 0.8079 | 1277.6 | 1412.1 | 0.034 |
| ops-p2 | mock-small | 2026-09-28 | 76396 | 0.8599 | 1377.2 | 1006.3 | 0.171 |
| plan-p2 | mock-large | 2026-10-01 | 76200 | 0.7411 | 4112.0 | 3472.2 | 0.209 |


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

Sample output - 8 row(s) shown from export, elapsed 274 ms, processed rows 22496:

| rule_id | rule_name | category | rule_severity | findings | blocked | flagged | affected_runs | affected_agents |
|---|---|---|---|---|---|---|---|---|
| SEC-004 | Prompt-injection indicator | prompt_injection | medium | 10974 | 0 | 10974 | 9966 | 4 |
| SEC-001 | Tool not on agent allowlist | tool_not_allowlisted | high | 3156 | 3156 | 0 | 2836 | 4 |
| SEC-002 | Prohibited action attempted | policy_violation | critical | 2711 | 2711 | 0 | 2704 | 4 |
| SEC-003 | Restricted data access | restricted_data_access | high | 1395 | 0 | 1395 | 1395 | 2 |
| SEC-005 | Sensitive data in output | sensitive_data_output | critical | 1301 | 0 | 1301 | 1300 | 4 |
| SEC-006 | Unexpected privilege transition | privilege_escalation | critical | 1299 | 0 | 1299 | 1299 | 4 |
| SEC-007 | Exfiltration-like sequence | exfiltration_sequence | critical | 1060 | 0 | 1060 | 1060 | 3 |
| SEC-008 | Tool-call budget exceeded | excessive_tool_calls | medium | 592 | 592 | 0 | 590 | 2 |

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

Sample output - 25 row(s) shown from export, elapsed 2170 ms, processed rows 5248219:

| event_time | rule_id | severity | agent_id | agent_version | run_id | trace_id | span_kind | span_name | tool_name | policy_decision | span_status | run_status | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-10T06:55:55.646253+00:00 | SEC-007 | critical | rag-helpdesk | 2.1.0 | R-2fa7eb-068882 | 2918544822be318e24cc4d200d1278bd | policy_check | output_guard | NULL | flag | ok | completed | sensitive read of SEC-001 followed by egress tool send_external_email |
| 2026-10-10T06:51:55.646247+00:00 | SEC-007 | critical | rag-helpdesk | 2.1.0 | R-e9b86d-068882 | ad07dede857d9aea4b92e10d64fafaa2 | policy_check | output_guard | NULL | flag | ok | completed | sensitive read of SEC-001 followed by egress tool send_external_email |
| 2026-10-10T06:45:50.741695+00:00 | SEC-007 | critical | rag-helpdesk | 2.0.0 | R-69ab72-343996 | 92550036b0a67f13256587c713de3734 | policy_check | output_guard | NULL | flag | ok | completed | sensitive read of FIN-001 followed by egress tool send_external_email |
| 2026-10-10T06:45:00.560788+00:00 | SEC-002 | critical | planner-agent | 2.0.0 | R-69ab72-343969 | 5ec5ec102280077af99900ad3976e92d | tool_call | tool:delete_records | delete_records | deny | error | completed | tool 'delete_records' is globally prohibited |
| 2026-10-10T06:41:01.623100+00:00 | SEC-002 | critical | ops-tool-agent | 1.0.0 | R-2fa7eb-068780 | 10f6d6fe6b116d3a3c60f27ad96f40bd | tool_call | tool:delete_records | delete_records | deny | error | completed | tool 'delete_records' is globally prohibited |
| 2026-10-10T06:40:01.019335+00:00 | SEC-002 | critical | ops-tool-agent | 1.1.0 | R-69ab72-343799 | 538117355dee5b26b8b4124f46250ae4 | tool_call | tool:modify_permissions | modify_permissions | deny | error | completed | tool 'modify_permissions' is globally prohibited |
| 2026-10-10T06:40:01.014649+00:00 | SEC-006 | critical | ops-tool-agent | 1.1.0 | R-69ab72-343799 | 538117355dee5b26b8b4124f46250ae4 | policy_check | role_monitor | NULL | flag | ok | completed | runtime role changed agent_runtime -> security_admin |
| 2026-10-10T06:38:34.930328+00:00 | SEC-002 | critical | ops-tool-agent | 1.0.0 | R-69ab72-343750 | 040b86c84b4a24fbe6573bd90161801f | tool_call | tool:export_data | export_data | deny | error | completed | tool 'export_data' is globally prohibited |
| 2026-10-10T06:37:01.623098+00:00 | SEC-002 | critical | ops-tool-agent | 1.0.0 | R-e9b86d-068780 | 192ad541919beac5313b206e6416cc6d | tool_call | tool:delete_records | delete_records | deny | error | completed | tool 'delete_records' is globally prohibited |
| 2026-10-10T06:34:04.615678+00:00 | SEC-007 | critical | ops-tool-agent | 1.1.0 | R-69ab72-343586 | 67e93ccfdf3d610a8c9e6b683a33ad55 | policy_check | output_guard | NULL | flag | ok | failed | sensitive read of finance/payroll followed by egress tool http_post |
| 2026-10-10T06:33:28.876349+00:00 | SEC-007 | critical | planner-agent | 2.0.0 | R-69ab72-343573 | 380769aa074775012ca723eaa359fff8 | policy_check | output_guard | NULL | flag | ok | failed | sensitive read of HR-001 followed by egress tool send_external_email |
| 2026-10-10T06:26:39.073759+00:00 | SEC-006 | critical | ops-tool-agent | 1.0.0 | R-2fa7eb-068682 | 7c6a0fa1c70c63d434e7ab5a097a8253 | policy_check | role_monitor | NULL | flag | ok | completed | runtime role changed agent_runtime -> root |

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

Sample output - 50 row(s) shown from export, elapsed 489 ms, processed rows 662876:

| run_id | trace_id | agent_name | agent_version | latency_ms | output_tokens | anomaly_type | anomaly_severity | rule_id | security_severity |
|---|---|---|---|---|---|---|---|---|---|
| R-6312db-005975 | ffac9848f7f8899174a6c64b27b82293 | QA Assistant | 1.1.0 | 637.304 | 164 | multivariate_outlier | medium | SEC-004 | medium |
| R-6312db-005975 | ffac9848f7f8899174a6c64b27b82293 | QA Assistant | 1.1.0 | 637.304 | 164 | multivariate_outlier | medium | SEC-002 | critical |
| R-a92ac1-011933 | 1cfb4af275bbe30e0a672658fb445988 | Planner Agent | 2.0.0 | 13405.602 | 1306 | multivariate_outlier | medium | SEC-008 | medium |
| R-a92ac1-011933 | 1cfb4af275bbe30e0a672658fb445988 | Planner Agent | 2.0.0 | 13405.602 | 1306 | suspected_loop | high | SEC-008 | medium |
| R-a92ac1-011933 | 1cfb4af275bbe30e0a672658fb445988 | Planner Agent | 2.0.0 | 13405.602 | 1306 | long_execution_chain | medium | SEC-008 | medium |
| R-6312db-005934 | 59cdc02c0b0853ba42d4b9f12941c311 | QA Assistant | 1.0.0 | 511.356 | 87 | multivariate_outlier | low | SEC-002 | critical |
| R-6312db-005912 | a7abb9a5c9546f1954c141df34d48d15 | QA Assistant | 1.1.0 | 802.255 | 188 | multivariate_outlier | medium | SEC-002 | critical |
| R-6312db-005912 | a7abb9a5c9546f1954c141df34d48d15 | QA Assistant | 1.1.0 | 802.255 | 188 | multivariate_outlier | medium | SEC-004 | medium |
| R-83cb19-019949 | 8a0fd3f36fd9926eb57134a5bf39f520 | QA Assistant | 1.0.0 | 524.666 | 104 | multivariate_outlier | low | SEC-002 | critical |
| R-5b93e7-011878 | cf5810ba53b4135bb4f3affa1f8d302c | Ops Tool Agent | 1.1.0 | 4437.651 | 428 | token_cost_spike | low | SEC-008 | medium |
| R-5b93e7-011878 | cf5810ba53b4135bb4f3affa1f8d302c | Ops Tool Agent | 1.1.0 | 4437.651 | 428 | suspected_loop | high | SEC-008 | medium |
| R-5b93e7-011878 | cf5810ba53b4135bb4f3affa1f8d302c | Ops Tool Agent | 1.1.0 | 4437.651 | 428 | multivariate_outlier | medium | SEC-008 | medium |

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

Sample output - 20 row(s) shown from export, elapsed 875 ms, processed rows 4632150:

| agent_version | hour | runs | p95_ms | tool_failures | findings | corr_p95_vs_tool_failures |
|---|---|---|---|---|---|---|
| 1.1.0 | 2026-10-09T14:00:00+00:00 | 735 | 2354.7 | 125 | 19 | 0.354 |
| 1.1.0 | 2026-10-09T04:00:00+00:00 | 582 | 2517.6 | 123 | 16 | 0.354 |
| 1.1.0 | 2026-10-09T10:00:00+00:00 | 723 | 2325.9 | 118 | 47 | 0.354 |
| 1.1.0 | 2026-10-09T12:00:00+00:00 | 718 | 2225.3 | 110 | 38 | 0.354 |
| 1.1.0 | 2026-10-09T08:00:00+00:00 | 699 | 2116.4 | 105 | 29 | 0.354 |
| 1.1.0 | 2026-10-08T21:00:00+00:00 | 592 | 2085.1 | 104 | 6 | 0.354 |
| 1.1.0 | 2026-10-09T18:00:00+00:00 | 681 | 2195.2 | 101 | 28 | 0.354 |
| 1.1.0 | 2026-10-08T16:00:00+00:00 | 439 | 2720.7 | 99 | 17 | 0.354 |
| 1.1.0 | 2026-10-09T07:00:00+00:00 | 648 | 2038.3 | 99 | 32 | 0.354 |
| 1.0.0 | 2026-10-09T08:00:00+00:00 | 722 | 2041.9 | 98 | 24 | 0.077 |
| 1.1.0 | 2026-10-09T09:00:00+00:00 | 728 | 2285.7 | 96 | 27 | 0.354 |
| 1.1.0 | 2026-10-09T16:00:00+00:00 | 692 | 2268.7 | 96 | 31 | 0.354 |

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

Sample output - 25 row(s) shown from export, elapsed 2006 ms, processed rows 3999817:

| trace_id | run_id | agent_id | first_sensitive_read | first_egress_attempt | tools_used |
|---|---|---|---|---|---|
| 2918544822be318e24cc4d200d1278bd | R-2fa7eb-068882 | rag-helpdesk | 2026-10-10T06:55:54.319875+00:00 | 2026-10-10T06:55:54.436058+00:00 | document_lookup,send_external_email |
| ad07dede857d9aea4b92e10d64fafaa2 | R-e9b86d-068882 | rag-helpdesk | 2026-10-10T06:51:54.319873+00:00 | 2026-10-10T06:51:54.436057+00:00 | document_lookup,send_external_email |
| 92550036b0a67f13256587c713de3734 | R-69ab72-343996 | rag-helpdesk | 2026-10-10T06:45:48.250024+00:00 | 2026-10-10T06:45:48.377506+00:00 | document_lookup,send_external_email |
| 67e93ccfdf3d610a8c9e6b683a33ad55 | R-69ab72-343586 | ops-tool-agent | 2026-10-10T06:33:48.072425+00:00 | 2026-10-10T06:33:48.076743+00:00 | read_resource,http_post,calculator |
| 380769aa074775012ca723eaa359fff8 | R-69ab72-343573 | planner-agent | 2026-10-10T06:33:25.271352+00:00 | 2026-10-10T06:33:25.363453+00:00 | document_lookup,send_external_email,delegate_subtask,search_kb,calculator |
| 80dc5766f2f29914120f4e0c3d31e20d | R-69ab72-343168 | planner-agent | 2026-10-10T06:21:34.981297+00:00 | 2026-10-10T06:21:35.118797+00:00 | document_lookup,send_external_email,get_order_status,create_ticket |
| 53db0e0ff7b486f172ef1eb607ab5309 | R-69ab72-342670 | ops-tool-agent | 2026-10-10T06:07:00.180069+00:00 | 2026-10-10T06:07:00.182781+00:00 | read_resource,send_external_email,create_ticket |
| 919e1237e6a29e73f39e2d02ee0bf083 | R-69ab72-342557 | ops-tool-agent | 2026-10-10T06:03:40.188307+00:00 | 2026-10-10T06:03:40.193231+00:00 | read_resource,send_external_email,create_ticket |
| b350806b0c86a21187b60b901865619f | R-69ab72-342404 | rag-helpdesk | 2026-10-10T05:59:13.056824+00:00 | 2026-10-10T05:59:13.187357+00:00 | document_lookup,send_external_email |
| 98b507622f7471c0b03a896f487758c0 | R-69ab72-342214 | ops-tool-agent | 2026-10-10T05:53:38.339254+00:00 | 2026-10-10T05:53:38.344295+00:00 | read_resource,send_external_email,search_kb |
| 1222e73fb5f9fe2c0577f536c6e89dc2 | R-69ab72-342041 | planner-agent | 2026-10-10T05:48:35.776368+00:00 | 2026-10-10T05:48:35.910284+00:00 | document_lookup,send_external_email,get_order_status |
| 2a9140cbf2385f98292225f5cb3ea488 | R-69ab72-341815 | rag-helpdesk | 2026-10-10T05:41:57.887730+00:00 | 2026-10-10T05:41:58.009000+00:00 | document_lookup,http_post |

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

Sample output - 7 row(s) shown from export, elapsed 1043 ms, processed rows 1285892:

| injected_scenario | expected_category | labelled_runs | detected_runs | detection_rate_pct | same_category_findings_on_unlabelled_runs |
|---|---|---|---|---|---|
| exfiltration_sequence | exfiltration_sequence | 1056 | 1056 | 100.0 | 0 |
| poisoned_document_retrieved | prompt_injection | 8033 | 8025 | 99.9 | 9 |
| policy_violation | policy_violation | 1257 | 1257 | 100.0 | 0 |
| privilege_escalation | privilege_escalation | 1298 | 1298 | 100.0 | 1 |
| prompt_injection | prompt_injection | 1937 | 1937 | 100.0 | 9 |
| sensitive_data_leak | sensitive_data_output | 1300 | 1300 | 100.0 | 0 |
| suspicious_tool_access | tool_not_allowlisted | 1789 | 1787 | 99.89 | 0 |

### security_residuals_vs_quarantine

**Are detection residuals explained by quarantined (corrupted) events?**

- **Question:** For labelled runs that lack the expected finding, and for findings on runs without labels, was one of the run's own events quarantined by the stream processor?
- **SQL concepts:** Residual analysis: anti-joins, regexp_extract on raw dead-letter payloads, equi-join to explain each residual
- **Interpretation:** Volume benchmarks inject ~0.1% corrupt records on purpose (and the truncation test 25%). A quarantined security.finding event looks like a missed detection; a quarantined run.metrics event drops the run's labels so its findings look unlabelled. Residuals with explained_by_quarantine = residual_runs are data-quality effects, not detector errors; unexplained residuals would need investigation.
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
missed AS (
    SELECT DISTINCT l.run_id, 'missed_detection' AS residual
    FROM labels l
    JOIN expected e ON e.label = l.label
    LEFT JOIN found f ON f.run_id = l.run_id AND f.category = e.category
    WHERE f.run_id IS NULL
),
unlabelled AS (
    SELECT DISTINCT f.run_id, 'finding_on_unlabelled_run' AS residual
    FROM found f
    WHERE f.category IN (SELECT category FROM expected)
      AND NOT EXISTS (SELECT 1 FROM labels l JOIN expected e ON e.label = l.label WHERE l.run_id = f.run_id)
),
quarantined_runs AS (
    SELECT DISTINCT regexp_extract(raw_value, '"run_id":"(R-[0-9a-f]{6}-[0-9]{6})"', 1) AS run_id
    FROM lakehouse.analytics.dead_letter_events
    WHERE ingest_date >= current_date - (:days * INTERVAL '1' DAY)
)
SELECT
    r.residual,
    count(*)                       AS residual_runs,
    count(q.run_id)                AS explained_by_quarantine,
    count(*) - count(q.run_id)     AS unexplained
FROM (SELECT * FROM missed UNION ALL SELECT * FROM unlabelled) r
LEFT JOIN quarantined_runs q ON q.run_id = r.run_id
GROUP BY r.residual
ORDER BY r.residual
```

Sample output - 2 row(s) shown from export, elapsed 760 ms, processed rows 1297631:

| residual | residual_runs | explained_by_quarantine | unexplained |
|---|---|---|---|
| finding_on_unlabelled_run | 10 | 10 | 0 |
| missed_detection | 10 | 10 | 0 |


## 06_data_quality_checks.sql

### dq_scorecard

**Data-quality scorecard (one row per check)**

- **Question:** How healthy is the curated data overall?
- **SQL concepts:** CTE per check + UNION ALL into a single scorecard
- **Interpretation:** issue_rate_pct is issues / rows checked. Non-zero counts are expected when a scenario injects dirty data (dirty_rate > 0); compare them with the generator's dirty_injected summary.
- **Parameters:** `days=2`

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
    -- distinct over a 64-bit hash of event_id instead of the 36-char string: several times less memory;
    -- P(any collision) for ~10M ids is ~3e-6 (birthday bound n^2 / 2^65)
    SELECT 'duplicate_event_ids', count(*) - count(DISTINCT xxhash64(to_utf8(event_id))), count(*) FROM raw WHERE is_valid
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

Sample output - 7 row(s) shown from export, elapsed 2916 ms, processed rows 18582266:

| check_name | issues | rows_checked | issue_rate_pct | result |
|---|---|---|---|---|
| quarantined_records | 9611 | 3338779 | 0.2879 | REVIEW |
| orphan_spans | 2183 | 1261585 | 0.173 | REVIEW |
| duplicate_event_ids | 512 | 3329168 | 0.0154 | REVIEW |
| negative_span_durations | 177 | 1488143 | 0.0119 | REVIEW |
| future_event_times | 0 | 1488143 | 0.0 | PASS |
| end_before_start | 0 | 1488143 | 0.0 | PASS |
| null_trace_ids_in_spans | 0 | 1488143 | 0.0 | PASS |

### dq_null_ids

**Null identifiers per curated table**

- **Question:** Do any curated rows lack the shared keys every module relies on?
- **SQL concepts:** Conditional aggregation across UNION ALL of several fact tables
- **Interpretation:** Spark rejects events missing required context, so these should be zero; a non-zero value would indicate a contract change that bypassed validation.
- **Parameters:** `days=2`

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

Sample output - 4 row(s) shown from export, elapsed 503 ms, processed rows 3325247:

| table_name | rows_checked | null_event_id | null_run_id | null_trace_id | null_agent_id |
|---|---|---|---|---|---|
| agent_security_findings | 8711 | 0 | 0 | 0 | 0 |
| agent_run_metrics | 226542 | 0 | 0 | 0 | 0 |
| agent_evaluation_results | 1601851 | 0 | 0 | 0 | 0 |
| agent_spans | 1488143 | 0 | 0 | 0 | 0 |

### dq_duplicate_events

**Duplicate event IDs (at-least-once delivery / producer retries)**

- **Question:** Which event IDs were ingested more than once, and on which topics?
- **SQL concepts:** GROUP BY ... HAVING count(*) > 1
- **Interpretation:** Duplicates are expected under at-least-once delivery. Analytical queries that must be exact can de-duplicate with ROW_NUMBER() OVER (PARTITION BY event_id ...).
- **Parameters:** `days=2`

```sql
SELECT
    kafka_topic,
    event_type,
    count(*)            AS duplicated_event_ids,
    sum(copies - 1)     AS extra_copies
FROM (
    SELECT xxhash64(to_utf8(event_id)) AS event_key, kafka_topic, event_type, count(*) AS copies
    FROM lakehouse.analytics.raw_agent_events
    WHERE is_valid AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY xxhash64(to_utf8(event_id)), kafka_topic, event_type
    HAVING count(*) > 1
) d
GROUP BY kafka_topic, event_type
ORDER BY extra_copies DESC
```

Sample output - 4 row(s) shown from export, elapsed 1964 ms, processed rows 3338539:

| kafka_topic | event_type | duplicated_event_ids | extra_copies |
|---|---|---|---|
| agent-evaluations | evaluation.result | 262 | 262 |
| agent-traces | span.completed | 196 | 196 |
| agent-metrics | run.metrics | 49 | 49 |
| agent-security-events | security.finding | 5 | 5 |

### dq_orphan_spans

**Spans whose parent span is missing**

- **Question:** Which traces contain spans pointing to a parent that never arrived (or was quarantined)?
- **SQL concepts:** Anti-join (LEFT JOIN ... WHERE right side IS NULL)
- **Interpretation:** Orphans break the trace waterfall. Causes: corrupted parent IDs, or a parent event that was quarantined as structurally invalid (check dead_letter_events for the same trace).
- **Parameters:** `days=2`

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

Sample output - 6 row(s) shown from export, elapsed 1327 ms, processed rows 5487960:

| test_run_id | orphan_spans | affected_traces | example_trace_id |
|---|---|---|---|
| TR-20261010-fb4df8 | 1483 | 398 | 00f7abaf55d71e99fe79100fdda03948 |
| TR-20261010-69ab72 | 371 | 148 | 00f05b18fa75ff43c02b99f01750964c |
| TR-20261009-83cb19 | 113 | 36 | 026ee6aaeb04b9a98dc8a99a6120c6eb |
| TR-20261010-e9b86d | 80 | 35 | 060c912e86126cbd715f5bbf6bca50c7 |
| TR-20261010-2fa7eb | 80 | 35 | 080e0b30acb96e3f08ed01d84a61f868 |
| TR-20261009-34bcb1 | 56 | 29 | 0345f7f3fd00ddcbc47d05dc21910060 |

### dq_quarantine_reasons

**Quarantined (dead-letter) records by reason and day**

- **Question:** Why were records rejected by the stream processor, and is the rejection rate stable?
- **SQL concepts:** Aggregation over the dead-letter table
- **Interpretation:** Every rejected record is kept (raw bytes + reason) - nothing is silently dropped.
- **Parameters:** `days=2`

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

Sample output - 31 row(s) shown from export, elapsed 154 ms, processed rows 11735:

| ingest_date | validation_error | kafka_topic | records |
|---|---|---|---|
| 2026-10-10 | malformed_json | agent-evaluations | 3415 |
| 2026-10-10 | malformed_json | agent-traces | 3042 |
| 2026-10-10 | unknown_event_type | agent-evaluations | 818 |
| 2026-10-10 | missing_event_id | agent-evaluations | 791 |
| 2026-10-10 | invalid_event_time | agent-evaluations | 706 |
| 2026-10-10 | unknown_event_type | agent-traces | 503 |
| 2026-10-10 | invalid_event_time | agent-traces | 493 |
| 2026-10-10 | malformed_json | agent-metrics | 465 |
| 2026-10-10 | missing_event_id | agent-traces | 438 |
| 2026-10-10 | invalid_event_time | agent-metrics | 127 |
| 2026-10-10 | unknown_event_type | agent-metrics | 113 |
| 2026-10-10 | missing_event_id | agent-metrics | 109 |

_19 more rows not shown (full result in docs/sql_outputs)._

### dq_timestamp_checks

**Timestamp sanity: span ordering, clock skew and run-window consistency**

- **Question:** Are event timestamps plausible (ordered, not in the future, inside their test run's window)?
- **SQL concepts:** Interval arithmetic, joins to the test-run dimension
- **Interpretation:** For simulated runs event_time lies in the test run's simulated window; for realtime runs it lies between started_at and ended_at. Events outside indicate producer clock problems.
- **Parameters:** `days=2`

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

Sample output - 10 row(s) shown from export, elapsed 286 ms, processed rows 226562:

| test_run_id | time_mode | runs | end_before_start | future_events | outside_sim_window | avg_event_to_ingest_ms_realtime |
|---|---|---|---|---|---|---|
| TR-20261010-69ab72 | simulated | 112659 | 0 | 0 | 0 | NULL |
| TR-20261010-2fa7eb | simulated | 22528 | 0 | 0 | 0 | NULL |
| TR-20261010-e9b86d | simulated | 22500 | 0 | 0 | 0 | NULL |
| TR-20261009-34bcb1 | simulated | 17728 | 0 | 0 | 0 | NULL |
| TR-20261009-a92ac1 | simulated | 12000 | 0 | 0 | 0 | NULL |
| TR-20261009-5b93e7 | simulated | 12000 | 0 | 0 | 0 | NULL |
| TR-20261009-83cb19 | simulated | 11985 | 0 | 0 | 0 | NULL |
| TR-20261009-9b5cf2 | simulated | 8000 | 0 | 0 | 0 | NULL |
| TR-20261009-6312db | simulated | 6000 | 0 | 0 | 0 | NULL |
| TR-20261010-fb4df8 | simulated | 1142 | 0 | 0 | 0 | NULL |

### dq_run_span_consistency

**Run summary vs span facts consistency**

- **Question:** Does each run's reported span_count match the spans actually stored?
- **SQL concepts:** Join an aggregate of child facts back to the parent fact
- **Interpretation:** Mismatches indicate lost or duplicated span events (e.g. a quarantined span or a duplicate).
- **Parameters:** `days=2`

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

Sample output - 10 row(s) shown from export, elapsed 1316 ms, processed rows 1941685:

| test_run_id | runs | consistent_runs | runs_missing_spans | runs_with_extra_spans | consistency_pct |
|---|---|---|---|---|---|
| TR-20261010-69ab72 | 112659 | 112267 | 392 | 0 | 99.652 |
| TR-20261010-2fa7eb | 22528 | 22461 | 67 | 0 | 99.703 |
| TR-20261010-e9b86d | 22500 | 22433 | 67 | 0 | 99.702 |
| TR-20261009-34bcb1 | 17728 | 17676 | 52 | 0 | 99.707 |
| TR-20261009-a92ac1 | 12000 | 12000 | 0 | 0 | 100.0 |
| TR-20261009-5b93e7 | 12000 | 12000 | 0 | 0 | 100.0 |
| TR-20261009-83cb19 | 11985 | 11882 | 103 | 0 | 99.141 |
| TR-20261009-9b5cf2 | 8000 | 8000 | 0 | 0 | 100.0 |
| TR-20261009-6312db | 6000 | 6000 | 0 | 0 | 100.0 |
| TR-20261010-fb4df8 | 1142 | 195 | 947 | 0 | 17.075 |


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

Sample output - 20 row(s) shown from export, elapsed 253 ms, processed rows 609950:

| event_date | agent_id | agent_version | runs_direct | runs_summary | successes_match | p95_direct | p95_from_merged_tdigest | p95_diff_pct |
|---|---|---|---|---|---|---|---|---|
| 2026-10-10 | rag-helpdesk | 2.1.0 | 2864 | 2864 | True | 2097.8 | 2101.6 | 0.18 |
| 2026-10-10 | planner-agent | 2.0.0 | 2741 | 2741 | True | 6227.6 | 6188.1 | -0.64 |
| 2026-10-10 | qa-assistant | 1.0.0 | 2639 | 2639 | True | 1170.7 | 1172.2 | 0.13 |
| 2026-10-10 | planner-agent | 1.0.0 | 2467 | 2467 | True | 5570.5 | 5588.7 | 0.33 |
| 2026-10-10 | qa-assistant | 1.1.0 | 2892 | 2892 | True | 1547.5 | 1551.2 | 0.24 |
| 2026-10-10 | ops-tool-agent | 1.1.0 | 2780 | 2780 | True | 1976.3 | 1978.3 | 0.1 |
| 2026-10-10 | ops-tool-agent | 1.0.0 | 2339 | 2339 | True | 1693.2 | 1693.1 | -0.0 |
| 2026-10-10 | rag-helpdesk | 2.0.0 | 2399 | 2399 | True | 2404.9 | 2407.1 | 0.09 |
| 2026-10-09 | planner-agent | 2.0.0 | 14658 | 14658 | True | 6497.3 | 6518.4 | 0.33 |
| 2026-10-09 | qa-assistant | 1.0.0 | 14418 | 14418 | True | 1219.4 | 1222.0 | 0.21 |
| 2026-10-09 | rag-helpdesk | 2.1.0 | 14387 | 14387 | True | 2178.4 | 2187.9 | 0.44 |
| 2026-10-09 | rag-helpdesk | 2.0.0 | 14520 | 14520 | True | 2529.8 | 2541.4 | 0.46 |

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

Sample output - 72 row(s) shown from export, elapsed 78 ms, processed rows 72:

| event_date | agent_name | agent_version | runs | success_rate | p95_latency_ms | est_cost_usd | security_findings | success_delta_vs_prev_day |
|---|---|---|---|---|---|---|---|---|
| 2026-10-02 | Ops Tool Agent | 1.0.0 | 231 | 0.9221 | 1771.0 | 0.0416 | 6 | NULL |
| 2026-10-03 | Ops Tool Agent | 1.0.0 | 7244 | 0.9197 | 1775.2 | 1.3187 | 203 | -0.0024 |
| 2026-10-04 | Ops Tool Agent | 1.0.0 | 9649 | 0.9118 | 1778.0 | 1.776 | 253 | -0.0079 |
| 2026-10-05 | Ops Tool Agent | 1.0.0 | 9852 | 0.9191 | 1782.8 | 1.7987 | 241 | 0.0073 |
| 2026-10-06 | Ops Tool Agent | 1.0.0 | 10003 | 0.9191 | 1779.2 | 1.8281 | 216 | 0.0 |
| 2026-10-07 | Ops Tool Agent | 1.0.0 | 10634 | 0.9039 | 1781.8 | 1.9651 | 282 | -0.0152 |
| 2026-10-08 | Ops Tool Agent | 1.0.0 | 11253 | 0.9085 | 1817.8 | 2.0958 | 239 | 0.0046 |
| 2026-10-09 | Ops Tool Agent | 1.0.0 | 14367 | 0.9144 | 1838.5 | 2.6575 | 439 | 0.0059 |
| 2026-10-10 | Ops Tool Agent | 1.0.0 | 2339 | 0.9158 | 1693.1 | 0.4259 | 73 | 0.0014 |
| 2026-10-02 | Ops Tool Agent | 1.1.0 | 252 | 0.8373 | 2167.5 | 0.0614 | 12 | NULL |
| 2026-10-03 | Ops Tool Agent | 1.1.0 | 7258 | 0.8611 | 2079.7 | 1.7435 | 213 | 0.0238 |
| 2026-10-04 | Ops Tool Agent | 1.1.0 | 9889 | 0.8653 | 2095.4 | 2.3651 | 211 | 0.0042 |

_60 more rows not shown (full result in docs/sql_outputs)._


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

Sample output - 1 row(s) shown from export, elapsed 93 ms, processed rows 0:

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
       │   Estimates: {rows: ? (?), cpu: 9.07M, memory: ?, network: 0B}
       │   count := count(count_1)
       │   approx_percentile := approx_percentile(approx_percentile_2)
       └─ LocalExchange[partitioning = HASH, arguments = [agent_id::varchar]]
          │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
          │   Estimates: {rows: 136387 (9.07MB), cpu: 9.07M, memory: 0B, network: 0B}
          └─ RemoteSource[sourceFragmentIds = [1]]
                 Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]

Fragment 1 [SOURCE]
    Output layout: [agent_id, count_1, approx_percentile_2]
    Output partitioning: HASH [agent_id]
    Aggregate[type = PARTIAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
    │   Estimates: {rows: 136387 (9.07MB), cpu: ?, memory: ?, network: ?}
    │   count_1 := count(*)
    │   approx_percentile_2 := approx_percentile(latency_ms, expr_0)
    └─ ScanProject[table = lakehouse:analytics.agent_run_metrics$data@7580205589668344724 constraint on [event_date]]
           Layout: [latency_ms:double, expr_0:double, agent_id:varchar]
           Estimates: {rows: 136387 (3.09MB), cpu: 1.92M, memory: 0B, network: 0B}/{rows: 136387 (3.09MB), cpu: 3.09M, memory: 0B, network: 0B}
           expr_0 := double '0.95'
           agent_id := 5:agent_id:varchar
           latency_ms := 21:latency_ms:double
           20:event_date:date
               :: [[2026-10-09, <max>)]


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

Sample output - 1 row(s) shown from export, elapsed 201 ms, processed rows 21121:

```text
Trino version: 467
Queued: 264.28us, Analysis: 16.87ms, Planning: 25.10ms, Execution: 162.94ms
Fragment 1 [HASH]
    CPU: 3.50ms, Scheduled: 4.00ms, Blocked 704.38ms (Input: 349.17ms, Output: 0.00ns), Input: 16 rows (13.64kB); per task: avg.: 16.00 std.dev.: 0.00, Output: 4 rows (143B)
    Peak Memory: 1.88kB, Tasks count: 1; per task: max: 1.88kB
    Output layout: [agent_id, count, approx_percentile]
    Output partitioning: SINGLE []
    Aggregate[type = FINAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count:bigint, approx_percentile:double]
    │   Estimates: {rows: ? (?), cpu: 1.40M, memory: ?, network: 0B}
    │   CPU: 1.00ms (6.67%), Scheduled: 1.00ms (5.26%), Blocked: 0.00ns (0.00%), Output: 4 rows (143B)
    │   Input avg.: 1.00 rows, Input std.dev.: 300.00%
    │   count := count(count_1)
    │   approx_percentile := approx_percentile(approx_percentile_2)
    └─ LocalExchange[partitioning = HASH, arguments = [agent_id::varchar]]
       │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
       │   Estimates: {rows: 21121 (1.40MB), cpu: 1.40M, memory: 0B, network: 0B}
       │   CPU: 1.00ms (6.67%), Scheduled: 1.00ms (5.26%), Blocked: 355.00ms (50.43%), Output: 16 rows (13.64kB)
       │   Input avg.: 1.00 rows, Input std.dev.: 173.21%
       └─ RemoteSource[sourceFragmentIds = [2]]
              Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
              CPU: 0.00ns (0.00%), Scheduled: 0.00ns (0.00%), Blocked: 349.00ms (49.57%), Output: 16 rows (13.64kB)
              Input avg.: 1.00 rows, Input std.dev.: 173.21%

Fragment 2 [SOURCE]
    CPU: 13.39ms, Scheduled: 16.99ms, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 21121 rows (271.02kB); per task: avg.: 21121.00 std.dev.: 0.00, Output: 16 rows (13.64kB)
    Peak Memory: 310.94kB, Tasks count: 1; per task: max: 2.10MB
    Output layout: [agent_id, count_1, approx_percentile_2]
    Output partitioning: HASH [agent_id]
    Aggregate[type = PARTIAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
    │   Estimates: {rows: 21121 (1.40MB), cpu: ?, memory: ?, network: ?}
    │   CPU: 6.00ms (40.00%), Scheduled: 7.00ms (36.84%), Blocked: 0.00ns (0.00%), Output: 16 rows (13.64kB)
    │   Input avg.: 5280.25 rows, Input std.dev.: 99.51%
    │   count_1 := count(*)
    │   approx_percentile_2 := approx_percentile(latency_ms, expr_0)
    └─ ScanProject[table = lakehouse:analytics.agent_run_metrics$data@7580205589668344724 constraint on [event_date]]
           Layout: [latency_ms:double, expr_0:double, agent_id:varchar]
           Estimates: {rows: 21121 (489.88kB), cpu: 304.25k, memory: 0B, network: 0B}/{rows: 21121 (489.88kB), cpu: 489.88k, memory: 0B, network: 0B}
           CPU: 7.00ms (46.67%), Scheduled: 10.00ms (52.63%), Blocked: 0.00ns (0.00%), Output: 21121 rows (294.71kB)
           Input avg.: 5280.25 rows, Input std.dev.: 99.51%
           expr_0 := double '0.95'
           agent_id := 5:agent_id:varchar
           latency_ms := 21:latency_ms:double
           20:event_date:date
               :: [[2026-10-10, <max>)]
           Input: 21121 rows (271.02kB), Filtered: 0.00%, Physical input: 1.91MB, Physical input time: 331.61us


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

Sample output - 1 row(s) shown from export, elapsed 234 ms, processed rows 609878:

```text
Trino version: 467
Queued: 317.35us, Analysis: 17.92ms, Planning: 28.85ms, Execution: 191.92ms
Fragment 1 [HASH]
    CPU: 9.65ms, Scheduled: 10.66ms, Blocked 1.31s (Input: 647.05ms, Output: 0.00ns), Input: 275 rows (241.15kB); per task: avg.: 275.00 std.dev.: 0.00, Output: 4 rows (143B)
    Peak Memory: 1.88kB, Tasks count: 1; per task: max: 1.30MB
    Output layout: [agent_id, count, approx_percentile]
    Output partitioning: SINGLE []
    Aggregate[type = FINAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count:bigint, approx_percentile:double]
    │   Estimates: {rows: ? (?), cpu: 40.55M, memory: ?, network: 0B}
    │   CPU: 6.00ms (2.05%), Scheduled: 6.00ms (1.71%), Blocked: 0.00ns (0.00%), Output: 4 rows (143B)
    │   Input avg.: 17.19 rows, Input std.dev.: 299.76%
    │   count := count(count_1)
    │   approx_percentile := approx_percentile(approx_percentile_2)
    └─ LocalExchange[partitioning = HASH, arguments = [agent_id::varchar]]
       │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
       │   Estimates: {rows: 609878 (40.55MB), cpu: 40.55M, memory: 0B, network: 0B}
       │   CPU: 1.00ms (0.34%), Scheduled: 2.00ms (0.57%), Blocked: 663.00ms (50.61%), Output: 275 rows (241.15kB)
       │   Input avg.: 17.19 rows, Input std.dev.: 162.25%
       └─ RemoteSource[sourceFragmentIds = [2]]
              Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
              CPU: 1.00ms (0.34%), Scheduled: 1.00ms (0.29%), Blocked: 647.00ms (49.39%), Output: 275 rows (241.15kB)
              Input avg.: 17.19 rows, Input std.dev.: 162.25%

Fragment 2 [SOURCE]
    CPU: 285.60ms, Scheduled: 340.89ms, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 609878 rows (7.61MB); per task: avg.: 609878.00 std.dev.: 0.00, Output: 275 rows (241.15kB)
    Peak Memory: 21.62MB, Tasks count: 1; per task: max: 21.62MB
    Output layout: [agent_id, count_1, approx_percentile_2]
    Output partitioning: HASH [agent_id]
    Aggregate[type = PARTIAL, keys = [agent_id]]
    │   Layout: [agent_id:varchar, count_1:bigint, approx_percentile_2:varbinary]
    │   Estimates: {rows: 609878 (40.55MB), cpu: ?, memory: ?, network: ?}
    │   CPU: 161.00ms (55.14%), Scheduled: 183.00ms (52.29%), Blocked: 0.00ns (0.00%), Output: 275 rows (241.15kB)
    │   Input avg.: 8838.81 rows, Input std.dev.: 73.80%
    │   count_1 := count(*)
    │   approx_percentile_2 := approx_percentile(latency_ms, expr_0)
    └─ ScanProject[table = lakehouse:analytics.agent_run_metrics$data@7580205589668344724]
           Layout: [latency_ms:double, expr_0:double, agent_id:varchar]
           Estimates: {rows: 609878 (13.80MB), cpu: 8.56M, memory: 0B, network: 0B}/{rows: 609878 (13.80MB), cpu: 13.80M, memory: 0B, network: 0B}
           CPU: 123.00ms (42.12%), Scheduled: 158.00ms (45.14%), Blocked: 0.00ns (0.00%), Output: 609878 rows (7.98MB)
           Input avg.: 8838.81 rows, Input std.dev.: 73.80%
           expr_0 := double '0.95'
           agent_id := 5:agent_id:varchar
           latency_ms := 21:latency_ms:double
           Input: 609878 rows (7.61MB), Filtered: 0.00%, Physical input: 54.21MB, Physical input time: 27.82ms


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

Sample output - 1 row(s) shown from export, elapsed 259 ms, processed rows 8961181:

```text
Trino version: 467
Queued: 318.08us, Analysis: 16.59ms, Planning: 24.21ms, Execution: 188.05ms
Fragment 1 [HASH]
    CPU: 13.95ms, Scheduled: 19.01ms, Blocked 4.27s (Input: 2.02s, Output: 0.00ns), Input: 500 rows (13.33kB); per task: avg.: 500.00 std.dev.: 0.00, Output: 10 rows (272B)
    Peak Memory: 1.88kB, Tasks count: 1; per task: max: 1.88kB
    Output layout: [event_type, count]
    Output partitioning: SINGLE []
    Aggregate[type = FINAL, keys = [event_type]]
    │   Layout: [event_type:varchar, count:bigint]
    │   Estimates: {rows: ? (?), cpu: 119.78M, memory: ?, network: 0B}
    │   CPU: 5.00ms (0.89%), Scheduled: 8.00ms (0.21%), Blocked: 0.00ns (0.00%), Output: 10 rows (272B)
    │   Input avg.: 31.25 rows, Input std.dev.: 166.72%
    │   count := count(count_0)
    └─ LocalExchange[partitioning = HASH, arguments = [event_type::varchar]]
       │   Layout: [event_type:varchar, count_0:bigint]
       │   Estimates: {rows: 8961181 (119.78MB), cpu: 119.78M, memory: 0B, network: 0B}
       │   CPU: 4.00ms (0.71%), Scheduled: 6.00ms (0.16%), Blocked: 2.25s (52.69%), Output: 500 rows (13.33kB)
       │   Input avg.: 31.25 rows, Input std.dev.: 98.05%
       └─ RemoteSource[sourceFragmentIds = [2]]
              Layout: [event_type:varchar, count_0:bigint]
              CPU: 1.00ms (0.18%), Scheduled: 1.00ms (0.03%), Blocked: 2.02s (47.31%), Output: 500 rows (13.33kB)
              Input avg.: 31.25 rows, Input std.dev.: 98.05%

Fragment 2 [SOURCE]
    CPU: 551.97ms, Scheduled: 3.80s, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 8961181 rows (34.25MB); per task: avg.: 8961181.00 std.dev.: 0.00, Output: 500 rows (13.33kB)
    Peak Memory: 675.85kB, Tasks count: 1; per task: max: 675.85kB
    Output layout: [event_type, count_0]
    Output partitioning: HASH [event_type]
    Aggregate[type = PARTIAL, keys = [event_type]]
    │   Layout: [event_type:varchar, count_0:bigint]
    │   Estimates: {rows: 8961181 (119.78MB), cpu: ?, memory: ?, network: ?}
    │   CPU: 124.00ms (22.14%), Scheduled: 287.00ms (7.55%), Blocked: 0.00ns (0.00%), Output: 500 rows (13.33kB)
    │   Input avg.: 87001.76 rows, Input std.dev.: 113.98%
    │   count_0 := count(*)
    └─ TableScan[table = lakehouse:analytics.raw_agent_events$data@7032857684663589456 constraint on [event_date]]
           Layout: [event_type:varchar]
           Estimates: {rows: 8961181 (42.86MB), cpu: 42.86M, memory: 0B, network: 0B}
           CPU: 426.00ms (76.07%), Scheduled: 3.50s (92.06%), Blocked: 0.00ns (0.00%), Output: 8961181 rows (34.25MB)
           Input avg.: 87001.76 rows, Input std.dev.: 113.98%
           event_type := 2:event_type:varchar
           5:event_date:date
               :: [[2026-08-11, <max>)]
           Input: 8961181 rows (34.25MB), Physical input: 20.60MB, Physical input time: 1.84s


```

### exp_tier_raw_json

**Tier 1 - daily success rate from raw JSON (schema-on-read)**

- **Question:** Daily success rate per agent version, computed directly from raw Kafka payloads.
- **SQL concepts:** JSON functions over the bronze table; full-column reads of raw_value
- **Interpretation:** Must read and parse the large raw_value column for every run.metrics event (slowest tier). Over the full ~9M-event history this query exceeds the 512 MB per-query memory budget and Trino stops it (measured by benchmarks/sql_benchmark.py); the curated and summary tiers answer the same question.
- **Parameters:** `days=3`

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

Sample output - 32 row(s) shown from export, elapsed 1415 ms, processed rows 4584561:

| event_date | agent_id | agent_version | runs | success_rate |
|---|---|---|---|---|
| 2026-10-07 | ops-tool-agent | 1.0.0 | 10634 | 0.9039 |
| 2026-10-07 | ops-tool-agent | 1.1.0 | 10804 | 0.8533 |
| 2026-10-07 | planner-agent | 1.0.0 | 10630 | 0.6335 |
| 2026-10-07 | planner-agent | 2.0.0 | 10577 | 0.7475 |
| 2026-10-07 | qa-assistant | 1.0.0 | 10688 | 0.8246 |
| 2026-10-07 | qa-assistant | 1.1.0 | 10703 | 0.9198 |
| 2026-10-07 | rag-helpdesk | 2.0.0 | 10566 | 0.8804 |
| 2026-10-07 | rag-helpdesk | 2.1.0 | 10752 | 0.8042 |
| 2026-10-08 | ops-tool-agent | 1.0.0 | 11253 | 0.9085 |
| 2026-10-08 | ops-tool-agent | 1.1.0 | 11223 | 0.861 |
| 2026-10-08 | planner-agent | 1.0.0 | 11245 | 0.6294 |
| 2026-10-08 | planner-agent | 2.0.0 | 11051 | 0.7369 |

_20 more rows not shown (full result in docs/sql_outputs)._

### exp_tier_curated

**Tier 2 - daily success rate from curated Iceberg facts**

- **Question:** Daily success rate per agent version from agent_run_metrics.
- **SQL concepts:** Typed columnar facts, partition pruning
- **Interpretation:** Reads two narrow typed columns (task_success, keys) instead of JSON text.
- **Parameters:** `days=3`

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

Sample output - 32 row(s) shown from export, elapsed 168 ms, processed rows 311896:

| event_date | agent_id | agent_version | runs | success_rate |
|---|---|---|---|---|
| 2026-10-07 | ops-tool-agent | 1.0.0 | 10634 | 0.9039 |
| 2026-10-07 | ops-tool-agent | 1.1.0 | 10804 | 0.8533 |
| 2026-10-07 | planner-agent | 1.0.0 | 10630 | 0.6335 |
| 2026-10-07 | planner-agent | 2.0.0 | 10577 | 0.7475 |
| 2026-10-07 | qa-assistant | 1.0.0 | 10688 | 0.8246 |
| 2026-10-07 | qa-assistant | 1.1.0 | 10703 | 0.9198 |
| 2026-10-07 | rag-helpdesk | 2.0.0 | 10566 | 0.8804 |
| 2026-10-07 | rag-helpdesk | 2.1.0 | 10752 | 0.8042 |
| 2026-10-08 | ops-tool-agent | 1.0.0 | 11253 | 0.9085 |
| 2026-10-08 | ops-tool-agent | 1.1.0 | 11223 | 0.861 |
| 2026-10-08 | planner-agent | 1.0.0 | 11245 | 0.6294 |
| 2026-10-08 | planner-agent | 2.0.0 | 11051 | 0.7369 |

_20 more rows not shown (full result in docs/sql_outputs)._

### exp_tier_summary

**Tier 3 - daily success rate from the pre-aggregated summary table**

- **Question:** Daily success rate per agent version from daily_agent_summary.
- **SQL concepts:** Materialised aggregate (one row per day x agent version)
- **Interpretation:** Reads a handful of pre-aggregated rows; freshness depends on the last summary refresh.
- **Parameters:** `days=3`

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

Sample output - 32 row(s) shown from export, elapsed 111 ms, processed rows 32:

| event_date | agent_id | agent_version | runs | success_rate |
|---|---|---|---|---|
| 2026-10-07 | ops-tool-agent | 1.0.0 | 10634 | 0.9039 |
| 2026-10-07 | ops-tool-agent | 1.1.0 | 10804 | 0.8533 |
| 2026-10-07 | planner-agent | 1.0.0 | 10630 | 0.6335 |
| 2026-10-07 | planner-agent | 2.0.0 | 10577 | 0.7475 |
| 2026-10-07 | qa-assistant | 1.0.0 | 10688 | 0.8246 |
| 2026-10-07 | qa-assistant | 1.1.0 | 10703 | 0.9198 |
| 2026-10-07 | rag-helpdesk | 2.0.0 | 10566 | 0.8804 |
| 2026-10-07 | rag-helpdesk | 2.1.0 | 10752 | 0.8042 |
| 2026-10-08 | ops-tool-agent | 1.0.0 | 11253 | 0.9085 |
| 2026-10-08 | ops-tool-agent | 1.1.0 | 11223 | 0.861 |
| 2026-10-08 | planner-agent | 1.0.0 | 11245 | 0.6294 |
| 2026-10-08 | planner-agent | 2.0.0 | 11051 | 0.7369 |

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

Sample output - 1 row(s) shown from export, elapsed 224 ms, processed rows 0:

```text
Trino version: 467
Queued: 277.95us, Analysis: 23.21ms, Planning: 49.00ms, Execution: 176.00ms
Fragment 1 [SOURCE]
    CPU: 67.29us, Scheduled: 73.59us, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 0 rows (0B); per task: avg.: 0.00 std.dev.: 0.00, Output: 0 rows (0B)
    Peak Memory: 0B, Tasks count: 1; per task: max: 0B
    Output layout: [span_id, span_kind, duration_ms]
    Output partitioning: SINGLE []
    ScanFilterProject[table = lakehouse:analytics.agent_spans$data@3573670507266723599, filterPredicate = (trace_id = varchar '00000000000000000000000000000000')]
        Layout: [span_id:varchar, span_kind:varchar, duration_ms:double]
        Estimates: {rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}
        CPU: 0.00ns (?%), Scheduled: 0.00ns (?%), Blocked: 0.00ns (?%), Output: 0 rows (0B)
        Input avg.: 0.00 rows, Input std.dev.: ?%
        span_kind := 10:span_kind:varchar
        span_id := 5:span_id:varchar
        duration_ms := 16:duration_ms:double
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

Sample output - 1 row(s) shown from export, elapsed 175 ms, processed rows 0:

```text
Trino version: 467
Queued: 273.14us, Analysis: 24.74ms, Planning: 24.47ms, Execution: 145.15ms
Fragment 1 [SOURCE]
    CPU: 59.65us, Scheduled: 65.32us, Blocked 0.00ns (Input: 0.00ns, Output: 0.00ns), Input: 0 rows (0B); per task: avg.: 0.00 std.dev.: 0.00, Output: 0 rows (0B)
    Peak Memory: 0B, Tasks count: 1; per task: max: 0B
    Output layout: [span_id, span_kind, duration_ms]
    Output partitioning: SINGLE []
    ScanFilterProject[table = lakehouse:analytics.agent_spans_sorted_by_trace$data@7345920503454343905, filterPredicate = (trace_id = varchar '00000000000000000000000000000000')]
        Layout: [span_id:varchar, span_kind:varchar, duration_ms:double]
        Estimates: {rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}/{rows: 0 (0B), cpu: 0, memory: 0B, network: 0B}
        CPU: 0.00ns (?%), Scheduled: 0.00ns (?%), Blocked: 0.00ns (?%), Output: 0 rows (0B)
        Input avg.: 0.00 rows, Input std.dev.: ?%
        span_kind := 10:span_kind:varchar
        span_id := 5:span_id:varchar
        duration_ms := 16:duration_ms:double
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

Sample output - 18 row(s) shown from export, elapsed 196 ms, processed rows 173:

| table_name | event_date | data_files | records | size_mb | avg_file_kb |
|---|---|---|---|---|---|
| agent_spans | 2026-10-02 | 1 | 12721 | 0.7 | 712.6 |
| agent_spans | 2026-10-03 | 5 | 384870 | 20.87 | 4275.1 |
| agent_spans | 2026-10-04 | 9 | 515345 | 28.04 | 3190.8 |
| agent_spans | 2026-10-05 | 7 | 515387 | 28.06 | 4105.4 |
| agent_spans | 2026-10-06 | 10 | 524873 | 28.64 | 2933.0 |
| agent_spans | 2026-10-07 | 10 | 558478 | 30.49 | 3121.8 |
| agent_spans | 2026-10-08 | 12 | 591070 | 32.22 | 2749.3 |
| agent_spans | 2026-10-09 | 12 | 759262 | 41.35 | 3528.2 |
| agent_spans | 2026-10-10 | 4 | 137811 | 7.52 | 1925.1 |
| raw_agent_events | 2026-10-02 | 1 | 28292 | 2.82 | 2890.2 |
| raw_agent_events | 2026-10-03 | 5 | 861928 | 84.45 | 17295.9 |
| raw_agent_events | 2026-10-04 | 9 | 1154175 | 113.4 | 12902.6 |

_6 more rows not shown (full result in docs/sql_outputs)._

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

Sample output - 6 row(s) shown from export, elapsed 449 ms, processed rows 390:

| table_name | files | records | size_mb | bytes_per_row |
|---|---|---|---|---|
| raw_agent_events | 103 | 8961181 | 882.52 | 103.3 |
| agent_spans | 70 | 3999817 | 217.89 | 57.1 |
| agent_evaluation_results | 70 | 4313012 | 157.55 | 38.3 |
| agent_run_metrics | 69 | 609878 | 54.21 | 93.2 |
| agent_security_findings | 69 | 22488 | 1.99 | 92.7 |
| daily_agent_summary | 9 | 72 | 0.03 | 448.6 |


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

Sample output - 15 row(s) shown from export, elapsed 114 ms, processed rows 35:

| committed_at | snapshot_id | operation | added_records | total_records | added_files | stream_batch_id |
|---|---|---|---|---|---|---|
| 2026-10-10T07:08:25.783000+00:00 | 7580205589668344724 | append | 1142 | 609878 | 1 | 36 |
| 2026-10-10T07:05:09.152000+00:00 | 5175773882797633479 | append | 17178 | 608736 | 2 | 35 |
| 2026-10-10T07:04:51.674000+00:00 | 982160633028685507 | append | 20439 | 591558 | 1 | 34 |
| 2026-10-10T07:04:35.348000+00:00 | 1869352004769412074 | append | 20445 | 571119 | 1 | 33 |
| 2026-10-10T07:04:17.655000+00:00 | 1115488065600930162 | append | 20446 | 550674 | 2 | 32 |
| 2026-10-10T07:04:02.898000+00:00 | 3951413464697779215 | append | 20443 | 530228 | 1 | 31 |
| 2026-10-10T07:03:46.725000+00:00 | 481830306155133114 | append | 20439 | 509785 | 2 | 30 |
| 2026-10-10T07:03:30.093000+00:00 | 6992442185831403451 | append | 20441 | 489346 | 1 | 29 |
| 2026-10-10T07:03:14.055000+00:00 | 3544043760243078471 | append | 20446 | 468905 | 2 | 28 |
| 2026-10-10T07:02:56.448000+00:00 | 6497557113050932923 | append | 20439 | 448459 | 2 | 27 |
| 2026-10-10T07:02:41.401000+00:00 | 7812107821544349603 | append | 20436 | 428020 | 1 | 26 |
| 2026-10-10T07:02:26.454000+00:00 | 979866748326691975 | append | 20434 | 407584 | 2 | 25 |

_3 more rows not shown (full result in docs/sql_outputs)._

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

Sample output - 2 row(s) shown from export, elapsed 110 ms, processed rows 1219756:

| version | runs |
|---|---|
| as of 1 minute ago | 609878 |
| current | 609878 |

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

Sample output - 2 row(s) shown from export, elapsed 110 ms, processed rows 1400:

| routing_strategy | rows_ |
|---|---|
| <NULL: written before ADD COLUMN> | 1000 |
| cost_aware | 400 |

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

Sample output - 3 row(s) shown from export, elapsed 69 ms, processed rows 3:

| committed_at | snapshot_id | parent_id | operation | added_records | total_records |
|---|---|---|---|---|---|
| 2026-10-10T07:14:28.295000+00:00 | 6025042864331053899 | NULL | append | 1000 | 1000 |
| 2026-10-10T07:14:30.185000+00:00 | 6654493009828756411 | 6025042864331053899 | append | 200 | 1200 |
| 2026-10-10T07:19:55.853000+00:00 | 2691945376669891251 | 6654493009828756411 | append | 200 | 1400 |

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

Sample output - 9 row(s) shown from export, elapsed 78 ms, processed rows 9:

| event_date | record_count | file_count | size_mb |
|---|---|---|---|
| 2026-10-02 | 12721 | 1 | 0.7 |
| 2026-10-03 | 384870 | 5 | 20.87 |
| 2026-10-04 | 515345 | 9 | 28.04 |
| 2026-10-05 | 515387 | 7 | 28.06 |
| 2026-10-06 | 524873 | 10 | 28.64 |
| 2026-10-07 | 558478 | 10 | 30.49 |
| 2026-10-08 | 591070 | 12 | 32.22 |
| 2026-10-09 | 759262 | 12 | 41.35 |
| 2026-10-10 | 137811 | 4 | 7.52 |
