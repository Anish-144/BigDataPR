-- =============================================================================
-- AgentShield lakehouse schema (Trino SQL -> Apache Iceberg tables, Parquet/ZSTD
-- files on MinIO). Executed by `lakehouse.run_sql` during `make init` / the
-- lakehouse-init container. Every statement is idempotent (IF NOT EXISTS).
--
-- Modelling choices
--   * Fact tables: raw_agent_events (bronze), agent_spans, agent_run_metrics,
--     agent_evaluation_results, agent_security_findings, agent_anomaly_alerts,
--     stream_agent_metrics_1m, pipeline_batch_metrics, dead_letter_events.
--   * Dimension / reference tables: agent_registry, agent_test_runs,
--     dim_model_pricing, dim_policy_rules, dim_scenarios, dim_date.
--   * Shared keys: test_run_id, run_id, trace_id, agent_id, agent_version,
--     scenario_id, event_time, event_date (UTC).
--   * Partitioning: identity partition on event_date (low cardinality, aligns
--     with the most common filter). We deliberately do NOT partition on
--     trace_id / agent_id (high cardinality -> tiny files).
--   * Iceberg format v2 (row-level deletes / MERGE support).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS lakehouse.analytics
WITH (location = 's3://warehouse/analytics');

-- -----------------------------------------------------------------------------
-- Bronze: every Kafka record exactly as received, valid or not.
-- Invalid records are kept here (is_valid = false) and copied to
-- dead_letter_events, so nothing is silently lost.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lakehouse.analytics.raw_agent_events (
    event_id          varchar,
    event_type        varchar,
    schema_version    varchar,
    event_time        timestamp(6) with time zone,
    event_date        date,
    test_run_id       varchar,
    run_id            varchar,
    trace_id          varchar,
    agent_id          varchar,
    agent_version     varchar,
    scenario_id       varchar,
    producer          varchar,
    kafka_topic       varchar,
    kafka_partition   integer,
    kafka_offset      bigint,
    kafka_timestamp   timestamp(6) with time zone,
    ingested_at       timestamp(6) with time zone,
    batch_id          bigint,
    is_valid          boolean,
    validation_error  varchar,
    raw_value         varchar
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.dead_letter_events (
    kafka_topic       varchar,
    kafka_partition   integer,
    kafka_offset      bigint,
    kafka_timestamp   timestamp(6) with time zone,
    event_id          varchar,
    event_type        varchar,
    validation_error  varchar,
    raw_value         varchar,
    ingested_at       timestamp(6) with time zone,
    ingest_date       date,
    batch_id          bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['ingest_date']);

-- -----------------------------------------------------------------------------
-- Silver: curated facts
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_spans (
    event_id             varchar,
    test_run_id          varchar,
    run_id               varchar,
    trace_id             varchar,
    span_id              varchar,
    parent_span_id       varchar,
    agent_id             varchar,
    agent_version        varchar,
    scenario_id          varchar,
    span_kind            varchar,
    span_name            varchar,
    start_time           timestamp(6) with time zone,
    end_time             timestamp(6) with time zone,
    event_time           timestamp(6) with time zone,
    event_date           date,
    duration_ms          double,
    status               varchar,
    error_category       varchar,
    step_index           integer,
    attempt              integer,
    depth                integer,
    model_name           varchar,
    input_tokens         integer,
    output_tokens        integer,
    ttft_ms              double,
    tool_name            varchar,
    tool_args_valid      boolean,
    tool_allowed         boolean,
    policy_decision      varchar,
    data_classification  varchar,
    retrieved_doc_ids    array(varchar),
    retrieval_scores     array(double),
    top_k                integer,
    delegated_agent_id   varchar,
    attributes           map(varchar, varchar),
    dq_flags             array(varchar),
    ingested_at          timestamp(6) with time zone,
    batch_id             bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_run_metrics (
    event_id                   varchar,
    test_run_id                varchar,
    run_id                     varchar,
    trace_id                   varchar,
    agent_id                   varchar,
    agent_name                 varchar,
    agent_version              varchar,
    agent_release_seq          integer,
    model_name                 varchar,
    prompt_version             varchar,
    workload_type              varchar,
    difficulty                 varchar,
    task_id                    varchar,
    scenario_id                varchar,
    status                     varchar,
    task_success               boolean,
    start_time                 timestamp(6) with time zone,
    end_time                   timestamp(6) with time zone,
    event_time                 timestamp(6) with time zone,
    event_date                 date,
    latency_ms                 double,
    ttft_ms                    double,
    input_tokens               bigint,
    output_tokens              bigint,
    total_tokens               bigint,
    tokens_per_second          double,
    llm_calls                  integer,
    tool_calls                 integer,
    tool_errors                integer,
    tool_timeouts              integer,
    tool_error_rate            double,
    retries                    integer,
    span_count                 integer,
    max_depth                  integer,
    distinct_tools             integer,
    max_consecutive_same_tool  integer,
    avg_tool_latency_ms        double,
    retrieval_count            integer,
    policy_denials             integer,
    error_category             varchar,
    estimated_cost_usd         double,       -- ESTIMATE from config/pricing.yaml (local, illustrative)
    cost_source                varchar,      -- local_pricing_config:<version> | unavailable
    injected_faults            array(varchar), -- synthetic ground-truth labels, never a detector input
    worker_id                  varchar,
    dq_flags                   array(varchar),
    ingested_at                timestamp(6) with time zone,
    batch_id                   bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_evaluation_results (
    event_id           varchar,
    evaluation_id      varchar,
    test_run_id        varchar,
    run_id             varchar,
    trace_id           varchar,
    agent_id           varchar,
    agent_version      varchar,
    scenario_id        varchar,
    event_time         timestamp(6) with time zone,
    event_date         date,
    evaluator_name     varchar,
    evaluator_version  varchar,
    evaluator_type     varchar,   -- deterministic | model_judge | human (never mixed)
    metric_name        varchar,
    score              double,
    passed             boolean,
    threshold          double,
    rubric             varchar,
    evidence           varchar,
    judge_model        varchar,
    ingested_at        timestamp(6) with time zone,
    batch_id           bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_security_findings (
    event_id        varchar,
    finding_id      varchar,
    test_run_id     varchar,
    run_id          varchar,
    trace_id        varchar,
    span_id         varchar,
    agent_id        varchar,
    agent_version   varchar,
    scenario_id     varchar,
    event_time      timestamp(6) with time zone,
    event_date      date,
    rule_id         varchar,
    rule_name       varchar,
    category        varchar,
    severity        varchar,
    tool_name       varchar,
    action          varchar,
    policy_version  varchar,
    detector        varchar,
    evidence        varchar,
    ingested_at     timestamp(6) with time zone,
    batch_id        bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_anomaly_alerts (
    event_id            varchar,
    alert_id            varchar,
    test_run_id         varchar,
    run_id              varchar,     -- set for per-run alerts, NULL for window alerts
    trace_id            varchar,
    agent_id            varchar,
    agent_name          varchar,
    agent_version       varchar,
    scenario_id         varchar,
    event_time          timestamp(6) with time zone,
    event_date          date,
    detector            varchar,
    detector_version    varchar,
    anomaly_type        varchar,
    severity            varchar,
    score               double,
    window_start        timestamp(6) with time zone,
    window_end          timestamp(6) with time zone,
    related_run_ids     array(varchar),
    related_trace_ids   array(varchar),
    supporting_metrics  map(varchar, double),
    explanation         varchar,
    ingested_at         timestamp(6) with time zone,
    batch_id            bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

-- Generator worker resource samples (CPU / memory of local test workers).
CREATE TABLE IF NOT EXISTS lakehouse.analytics.worker_resource_metrics (
    event_id         varchar,
    test_run_id      varchar,
    worker_id        varchar,
    event_time       timestamp(6) with time zone,
    event_date       date,
    cpu_percent      double,
    memory_mb        double,
    tasks_completed  bigint,
    events_emitted   bigint,
    events_per_sec   double,
    interval_s       double,
    ingested_at      timestamp(6) with time zone,
    batch_id         bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

-- Output of the Spark event-time windowed aggregation (1-minute tumbling
-- windows, watermark-finalised, append mode).
CREATE TABLE IF NOT EXISTS lakehouse.analytics.stream_agent_metrics_1m (
    window_start           timestamp(6) with time zone,
    window_end             timestamp(6) with time zone,
    event_date             date,
    agent_id               varchar,
    agent_version          varchar,
    runs                   bigint,
    successes              bigint,
    failures               bigint,
    timeouts               bigint,
    sum_latency_ms         double,
    max_latency_ms         double,
    approx_p95_latency_ms  double,
    total_tokens           bigint,
    tool_calls             bigint,
    tool_errors            bigint,
    retries                bigint,
    policy_denials         bigint,
    emitted_at             timestamp(6) with time zone,
    batch_id               bigint
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

-- One row per Spark micro-batch: throughput, validation and end-to-end lag.
CREATE TABLE IF NOT EXISTS lakehouse.analytics.pipeline_batch_metrics (
    query_name          varchar,
    batch_id            bigint,
    batch_start         timestamp(6) with time zone,
    batch_end           timestamp(6) with time zone,
    duration_ms         double,
    input_rows          bigint,
    valid_rows          bigint,
    invalid_rows        bigint,
    rows_written        map(varchar, bigint),
    min_kafka_ts        timestamp(6) with time zone,
    max_kafka_ts        timestamp(6) with time zone,
    avg_ingest_lag_ms   double,
    max_ingest_lag_ms   double,
    event_date          date
)
WITH (format = 'PARQUET', format_version = 2, partitioning = ARRAY['event_date']);

-- -----------------------------------------------------------------------------
-- Dimensions / reference data
-- -----------------------------------------------------------------------------
-- Upserted (MERGE) by the stream job from test_run.started / completed events.
CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_test_runs (
    test_run_id        varchar,
    test_run_name      varchar,
    status             varchar,
    seed               bigint,
    requested_tasks    bigint,
    workers            integer,
    time_mode          varchar,
    scenario_file      varchar,
    workload_mix       varchar,
    fault_profile      varchar,
    started_at         timestamp(6) with time zone,
    ended_at           timestamp(6) with time zone,
    sim_window_start   timestamp(6) with time zone,
    sim_window_end     timestamp(6) with time zone,
    total_runs         bigint,
    total_events       bigint,
    triggered_by       varchar,
    notes              varchar,
    last_event_time    timestamp(6) with time zone,
    updated_at         timestamp(6) with time zone
)
WITH (format = 'PARQUET', format_version = 2);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_registry (
    agent_id                 varchar,
    agent_name               varchar,
    workload_type            varchar,
    owner                    varchar,
    description              varchar,
    agent_version            varchar,
    release_seq              integer,   -- semantic ordering of versions
    released_at              date,
    model_name               varchar,
    prompt_version           varchar,
    allowed_tools            array(varchar),
    max_tool_calls           integer,
    max_data_classification  varchar,
    profile_json             varchar,
    registered_at            timestamp(6) with time zone
)
WITH (format = 'PARQUET', format_version = 2);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.dim_model_pricing (
    model_name            varchar,
    input_per_1k_tokens   double,
    output_per_1k_tokens  double,
    currency              varchar,
    pricing_version       varchar,
    disclaimer            varchar
)
WITH (format = 'PARQUET', format_version = 2);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.dim_policy_rules (
    rule_id         varchar,
    rule_name       varchar,
    category        varchar,
    severity        varchar,
    description     varchar,
    policy_version  varchar
)
WITH (format = 'PARQUET', format_version = 2);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.dim_scenarios (
    scenario_id    varchar,
    description    varchar,
    seed           bigint,
    default_tasks  bigint,
    time_mode      varchar,
    sim_days       double,
    workload_mix   varchar,
    fault_profile  varchar,
    scenario_file  varchar
)
WITH (format = 'PARQUET', format_version = 2);

CREATE TABLE IF NOT EXISTS lakehouse.analytics.dim_date (
    date_key     date,
    year         integer,
    month        integer,
    day          integer,
    day_of_week  integer,
    day_name     varchar,
    is_weekend   boolean
)
WITH (format = 'PARQUET', format_version = 2);

-- Regression-gate results: one row per (gate run x check). Written by
-- evaluation/regression_gate.py (CLI, API, Airflow daily_agent_regression).
CREATE TABLE IF NOT EXISTS lakehouse.analytics.agent_regression_results (
    gate_id            varchar,
    evaluated_at       timestamp(6) with time zone,
    agent_id           varchar,
    baseline_version   varchar,
    candidate_version  varchar,
    scenario_id        varchar,
    test_run_id        varchar,
    check_name         varchar,
    unit               varchar,
    baseline_value     double,
    candidate_value    double,
    delta              double,
    review_threshold   double,
    fail_threshold     double,
    check_status       varchar,   -- pass | review | fail | skipped
    verdict            varchar,   -- PASSED | NEEDS_REVIEW | FAILED | INSUFFICIENT_DATA
    baseline_runs      bigint,
    candidate_runs     bigint,
    success_p_value    double,    -- two-proportion z-test (informational)
    note               varchar,
    thresholds_source  varchar
)
WITH (format = 'PARQUET', format_version = 2);
