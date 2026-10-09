# AgentShield — Master Project Specification & Claude Code Build Prompt

**Project title:** AgentShield: A Big Data Platform for AI Agent Performance Benchmarking, Reliability Evaluation, Anomaly Detection, and Security Governance  
**Project type:** Final-year / college Big Data + AI engineering project  
**Team:** 4 members  
**Target implementation window:** 45 days  
**Primary goal:** Build one integrated platform that can test, measure, monitor, and secure autonomous AI agents using a demonstrable Big Data lakehouse architecture.

---

## 1. Product vision

AgentShield is an AI-agent testing and observability platform. It runs controlled agent workloads, collects execution telemetry, processes high-volume events, evaluates quality and reliability, detects performance and behavioral anomalies, and identifies security-policy violations. It then presents evidence-backed findings and recommendations through a single web dashboard.

This is **not merely a SOC dashboard** and not merely a benchmark script. Its differentiator is the combination of:

1. **Big Data engineering:** event streaming, distributed processing, a lakehouse, and analytical SQL.
2. **AI agent evaluation:** task success, answer quality, RAG quality, tool-call correctness, latency, and cost.
3. **ML-driven anomaly detection:** latency/cost regressions, loops, error spikes, drift, and unusual tool behavior.
4. **AI security and governance:** suspicious tool use, prompt-injection indicators, data-access violations, and policy breaches.
5. **AI-assisted investigation:** trace-grounded explanations and recommended next steps.

Use a shared telemetry model so the same agent execution can be analyzed from performance, quality, and security perspectives.

### Suggested project abstract

Autonomous AI agents combine language models, retrieval systems, memory, and tools, creating complex execution paths that are difficult to test and monitor with conventional application metrics alone. AgentShield is a Big Data platform that captures agent execution telemetry and processes it through a distributed streaming and lakehouse architecture. It measures performance, cost, task quality, and reliability; detects anomalous execution patterns; and surfaces security and governance findings. A SQL analytics layer enables large-scale trend analysis and comparisons across models, prompts, agent versions, and test runs. An AI-assisted investigation module summarizes trace evidence and recommends improvements. The platform will be evaluated using repeatable synthetic workloads at increasing event volumes, with reported throughput, processing latency, query latency, detection quality, and evaluation metrics.

---

## 2. Product requirements

### 2.1 Testing lab and workload runner

Build a controlled test lab for instrumented sample agents. Support at least these workload types:

- Simple question-answering agent.
- RAG/document question-answering agent.
- Tool-using agent that calls mock tools such as search, calculator, document lookup, or ticket creation.
- Multi-step agent simulation with planning, tool execution, retries, and final answer.
- Failure-injection workloads: slow tool, tool timeout, repeated call/loop, malformed response, high token usage, failed retrieval, suspicious tool access, and policy violation.

Provide configurable test scenarios:
- Number of tasks and concurrent workers.
- Agent/model/prompt version labels.
- Workload mix and difficulty.
- Artificial latency, timeout, error, and tool failure rates.
- Expected outcomes / reference answers where appropriate.
- Security-policy test cases.

The system must work without paid model APIs. Use deterministic mock agents and synthetic telemetry as the default so demos and benchmarks are repeatable. Optionally add an adapter for a real LLM provider through environment variables; the platform must remain functional when no API key is present.

### 2.2 Performance metrics

Capture and show:
- Total tasks and total agent runs.
- Task success rate and failure rate.
- Average, median, p90, p95, and p99 latency.
- Time to first token where available.
- Events/second and tasks/second.
- Input and output token counts; estimated cost if a configured pricing table is available.
- Tool-call count, retries, timeout count, and average tool latency.
- Error rate and error categories.
- CPU/memory usage for local test workers where available.
- Streaming processing lag and batch duration.
- Trino query execution duration and rows scanned where available.

Never invent provider token costs. If pricing is not configured, show token counts and mark monetary cost as unavailable or estimated using an explicitly labelled local pricing configuration.

### 2.3 Quality and reliability evaluation

Implement a transparent evaluation pipeline with configurable metrics:
- Task completion / expected outcome match.
- Structured-output schema validity.
- Tool selection and tool argument correctness in deterministic test scenarios.
- RAG retrieval metrics where ground truth exists: Recall@K, Precision@K, and reciprocal rank / MRR.
- Groundedness or citation coverage for RAG answers where evidence is available.
- Hallucination indicators using reference checks and/or a clearly labelled optional LLM judge.
- Regression comparison between agent versions, prompts, model configurations, or retrieval settings.

Keep separate fields for deterministic metrics and model-judged scores. A model judge is probabilistic and must not be represented as ground truth. Store evaluator name, version, rubric, score, and evidence.

### 2.4 Anomaly detection

Implement a baseline detector and at least one ML detector:
- Rule-based thresholds for immediate, explainable alerts.
- Isolation Forest or a comparable scikit-learn unsupervised detector for anomalous execution windows or traces.
- Optional rolling baseline / drift check by agent version.

Candidate anomaly types:
- Latency or token-cost spike.
- Repeated tool calls / suspected loop.
- Sudden error or timeout increase.
- Unusually long execution chain.
- Unexpected tool sequence.
- Large deviation from an agent's historical profile.
- Retrieval quality or task-success regression.

Every alert should include severity, score, detector, time window, affected agent/version, related trace/run IDs, supporting metrics, and a human-readable explanation. Show false-positive limitations and allow the user to mark an alert as useful/noisy for later review. Do not claim that an anomaly is automatically a cyberattack.

### 2.5 Security and governance analytics

Implement safe, controlled detections using synthetic events and mock tools:
- Tool not on an agent's allowlist.
- Attempted access to restricted mock data.
- Prompt-injection indicator present in test input or retrieved document.
- Sensitive-data pattern in output (use synthetic canary values only).
- Excessive permissions or unexpected privilege transition in a simulated event.
- Data-exfiltration-like sequence in a synthetic scenario.
- Agent violates a configured policy or tries a disallowed action.

Use a configurable policy file, such as YAML or JSON, with allowed tools, data classifications, maximum tool calls, and prohibited actions. Keep security findings linked to the trace and policy rule. Treat input text as untrusted data; never execute tool instructions found inside it.

### 2.6 AI-assisted investigation

Add a retrieval-grounded investigation assistant that can answer questions such as:
- “Why did run R-104 fail?”
- “Compare agent version v1 and v2 for latency, cost, and task success.”
- “Show the main causes of timeouts during the last test.”
- “Why was this tool call flagged?”
- “What changed in the last regression run?”
- “Suggest improvements for the highest-cost agent.”

Ground answers in retrieved trace summaries, SQL aggregates, evaluation records, policy definitions, and local knowledge documents. Display evidence references (run IDs, trace IDs, metric windows, or document titles). If no evidence exists, say so. Do not let the LLM invent metrics or execute arbitrary SQL. Prefer a fixed set of parameterized query tools or validated read-only query templates.

For the 45-day scope, a simple RAG implementation using Sentence Transformers + FAISS or a similarly lightweight local vector index is sufficient. LLM provider integration is optional; a deterministic fallback summary must exist.

---

## 3. Big Data architecture (the core academic contribution)

Use a layered architecture with explicit data flow.

### 3.1 Recommended stack

| Layer | Technology | Purpose |
|---|---|---|
| Workload generation | Python | Reproducible agent tasks and synthetic event generation |
| Telemetry schema | JSON / Pydantic; OpenTelemetry-inspired fields | Consistent trace, span, metrics, and event model |
| Event ingestion | Apache Kafka | Decoupled, scalable event streaming |
| Stream processing | Apache Spark Structured Streaming | Windowed aggregations, enrichment, feature extraction, anomaly features |
| Lakehouse table format | Apache Iceberg | Table metadata, schema evolution, snapshots, analytics-friendly tables |
| File/object storage | Parquet on MinIO | Columnar storage and local S3-compatible object storage |
| Analytical SQL | Trino | Interactive SQL over lakehouse tables |
| Batch orchestration | Apache Airflow | Scheduled benchmark, regression, and model-training pipelines |
| Operational database | PostgreSQL | Users/configuration, test definitions, alert status, agent registry |
| Backend API | FastAPI | REST API, run orchestration, analytics access |
| Frontend | React + Vite + TypeScript + Tailwind | Testing lab and analytics dashboard |
| ML | scikit-learn | Isolation Forest, baseline metrics, classification/evaluation |
| Retrieval | Sentence Transformers + FAISS (optional) | Trace/knowledge retrieval for investigation assistant |
| Packaging | Docker Compose | Reproducible local deployment |

Use compatible pinned versions and document them. Prefer a working, testable subset over an overcomplicated cluster. A local single-node Docker Compose setup is acceptable for the college demonstration, provided the architecture demonstrates distributed-style processing and is benchmarked honestly. Do not claim true multi-node scaling if only one machine is used.

### 3.2 Logical data flow

1. The test runner starts a test run and emits task, agent, LLM-call, retrieval, tool-call, evaluation, and security events.
2. Events are validated and published to Kafka topics.
3. Spark Structured Streaming reads topics, validates/normalizes events, enriches them with agent/run metadata, computes time-window aggregates and features, and writes curated records.
4. Raw and curated events are stored as Parquet-backed Iceberg tables on MinIO.
5. Trino queries Iceberg tables with SQL for dashboards, comparisons, trends, cohorts, and benchmark reports.
6. Airflow schedules regression runs, batch evaluations, model refreshes, data-quality checks, and maintenance tasks.
7. FastAPI serves run controls and query results; React displays interactive views.
8. The investigation assistant uses query results and trace/document retrieval to explain findings with evidence.

### 3.3 Kafka topics

Create and document a manageable topic set:
- `agent-traces` — run/span lifecycle and parent-child trace relationships.
- `agent-metrics` — latency, token usage, resource, and throughput measurements.
- `agent-evaluations` — task outcome and quality-evaluation records.
- `agent-security-events` — policy violations and suspicious activity.
- `agent-alerts` — normalized alert records produced by processing/detection.

Use stable event IDs, timestamps, run IDs, trace IDs, agent IDs, and version fields. Add producer/consumer health checks, retry handling, and dead-letter/error handling if feasible.

### 3.4 Lakehouse table design

Create at least these tables:
- `raw_agent_events`
- `agent_spans`
- `agent_run_metrics`
- `agent_evaluation_results`
- `agent_security_findings`
- `agent_anomaly_alerts`
- `agent_test_runs`
- `agent_registry`
- `daily_agent_summary` or `hourly_agent_summary`

Recommended model:
- **Fact tables:** spans, evaluations, metrics, anomalies, security findings.
- **Dimension/reference tables:** agents, versions, test scenarios, model configurations, policy rules, calendar/time.
- Use `run_id`, `trace_id`, `agent_id`, `agent_version`, `scenario_id`, `event_time`, and `event_date` consistently.
- Use Parquet columnar storage and partition by time/date where useful. Avoid high-cardinality partitioning on `trace_id` or `agent_id`.
- Demonstrate schema evolution with a safe optional field added to an event/table.
- Document retention and synthetic-data privacy assumptions.
- If supported by the selected Iceberg setup, demonstrate snapshot history/time travel or rollback in a non-production test.

---

## 4. Big Data SQL: make this visible to faculty

SQL must be a first-class project feature, not just an implementation detail. Use **Trino SQL over Iceberg/Parquet** for analytical queries and **Spark SQL** for distributed transformations. Keep the SQL scripts in a dedicated `sql/` directory, with comments explaining the analytical question and expected interpretation.

### 4.1 Required SQL demonstrations

1. **CTEs and multi-table joins:** combine run, agent, evaluation, and span data.
2. **Window functions:** rank agents by p95 latency or cost within a model/version group.
3. **Time-window trend analysis:** hourly/daily task success, latency, and event volume.
4. **Percentiles:** median, p90, p95, and p99 latency (use supported percentile functions; document any approximation).
5. **Conditional aggregation:** compare pass/fail, alert severities, and tool-call outcomes.
6. **Top-N and ranking:** most expensive agents, most common failures, highest-risk scenarios.
7. **Cohort comparison:** model/prompt/agent version A vs B.
8. **Data quality SQL:** null IDs, duplicate event IDs, negative durations, missing parent spans, invalid timestamps.
9. **Anomaly correlation:** join performance regressions with tool errors and security findings by trace/run/time window.
10. **Cost and efficiency analysis:** cost or token usage per successful task, not just per request.
11. **Materialized/summary tables:** pre-aggregate daily/hourly metrics and compare query performance against raw-event queries.
12. **Query-plan demonstration:** use `EXPLAIN` and discuss partition pruning, columnar reads, and the effect of table layout. Only report improvements actually measured.

### 4.2 Example Trino SQL: p95 latency by agent version

Adapt field/table names to the final schema.

```sql
SELECT
    agent_name,
    agent_version,
    COUNT(*) AS completed_runs,
    ROUND(AVG(latency_ms), 2) AS avg_latency_ms,
    approx_percentile(latency_ms, 0.95) AS p95_latency_ms,
    ROUND(AVG(input_tokens + output_tokens), 2) AS avg_tokens
FROM lakehouse.analytics.agent_run_metrics
WHERE event_date >= CURRENT_DATE - INTERVAL '7' DAY
  AND status = 'completed'
GROUP BY agent_name, agent_version
ORDER BY p95_latency_ms DESC;
```

### 4.3 Example SQL: regression ranking using a window function

```sql
WITH version_metrics AS (
    SELECT
        agent_name,
        agent_version,
        AVG(latency_ms) AS avg_latency_ms,
        AVG(CASE WHEN task_success THEN 1.0 ELSE 0.0 END) AS success_rate,
        AVG(input_tokens + output_tokens) AS avg_tokens
    FROM lakehouse.analytics.agent_run_metrics
    GROUP BY agent_name, agent_version
),
ranked AS (
    SELECT
        *,
        LAG(avg_latency_ms) OVER (
            PARTITION BY agent_name
            ORDER BY agent_version
        ) AS previous_version_latency,
        RANK() OVER (
            PARTITION BY agent_name
            ORDER BY success_rate DESC
        ) AS success_rank
    FROM version_metrics
)
SELECT
    agent_name,
    agent_version,
    avg_latency_ms,
    previous_version_latency,
    ROUND(
        100.0 * (avg_latency_ms - previous_version_latency)
        / NULLIF(previous_version_latency, 0), 2
    ) AS latency_change_pct,
    success_rate,
    avg_tokens,
    success_rank
FROM ranked
ORDER BY latency_change_pct DESC NULLS LAST;
```

Note: lexical version ordering is not always semantic version ordering. Store a numeric release sequence or deployment timestamp and order by that field in the actual implementation.

### 4.4 Example SQL: correlate anomalies with security findings

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
WHERE a.alert_id IS NOT NULL
   OR s.finding_id IS NOT NULL
ORDER BY m.event_time DESC;
```

### 4.5 Example SQL: cost efficiency per successful task

```sql
SELECT
    agent_name,
    agent_version,
    SUM(estimated_cost_usd) AS total_estimated_cost_usd,
    SUM(CASE WHEN task_success THEN 1 ELSE 0 END) AS successful_tasks,
    SUM(estimated_cost_usd)
      / NULLIF(SUM(CASE WHEN task_success THEN 1 ELSE 0 END), 0)
      AS estimated_cost_per_success
FROM lakehouse.analytics.agent_run_metrics
GROUP BY agent_name, agent_version
ORDER BY estimated_cost_per_success ASC NULLS LAST;
```

All monetary fields must be clearly marked as estimates and use a documented local pricing configuration. Do not silently assume current commercial model pricing.

### 4.6 SQL deliverables

Include:
- `sql/01_schema_and_tables.sql`
- `sql/02_performance_analytics.sql`
- `sql/03_window_functions_and_rankings.sql`
- `sql/04_regression_comparison.sql`
- `sql/05_security_correlation.sql`
- `sql/06_data_quality_checks.sql`
- `sql/07_summary_tables.sql`
- `sql/08_query_plan_experiments.sql`
- A `docs/SQL_SHOWCASE.md` with the question, SQL concept, query, sample output, and interpretation for each showcase.
- Screenshots or exports of query results for the final presentation.

---

## 5. Current AI trends to incorporate sensibly

The goal is to demonstrate relevant AI engineering practices without turning the project into a collection of buzzwords.

### 5.1 Agent observability and OpenTelemetry-inspired traces

Represent a run as a trace containing related spans: agent start/end, model call, retrieval, tool call, evaluation, and policy check. Capture duration, status, parent span, model/agent version, token counts when available, and error category. Use OpenTelemetry GenAI semantic conventions as a reference for naming and structure, while documenting any project-specific extensions.

Do not store raw prompts and completions by default. Synthetic test content is fine; for real content, make capture configurable and apply redaction/access controls.

### 5.2 Evaluation-driven development and regression testing

Every important agent change should be evaluated against a repeatable dataset of test cases. Compare success rate, quality scores, p95 latency, token usage, and security-policy outcomes before and after a change. Set configurable thresholds and mark a run as passed, failed, or needs review.

### 5.3 LLM-as-a-judge (optional and labelled)

Use a model judge only where deterministic checks are insufficient, such as groundedness or answer relevance. Store the rubric, judge model/version, score, explanation, and evaluator configuration. Include a small human-reviewed sample or deterministic benchmark to check judge consistency. Never treat a judge score as an objective fact.

### 5.4 RAG evaluation

For the RAG agent, capture retrieved document IDs, rank, retrieval score, answer references, and expected source when available. Measure Recall@K / MRR for retrieval and groundedness/citation coverage for generated answers. Provide an evidence panel showing which documents supported a result.

### 5.5 Guardrails and policy-aware tool use

Use allowlists and structured tool schemas for mock tools. Log the tool requested, whether it was allowed, the policy decision, and the result. Include synthetic prompt-injection and sensitive-data test cases. Avoid executing untrusted instructions or enabling unrestricted shell, filesystem, or network tools.

### 5.6 Cost-aware and latency-aware AI engineering

Expose token use, request duration, tool latency, retries, and estimated cost per successful task. Support comparison between configurations. Track time-to-first-token only when the selected agent/provider actually exposes it.

### 5.7 Optional advanced trends

Only implement these after core requirements work:
- Multi-agent trace visualization / agent-to-agent delegation.
- A small model-routing experiment comparing quality, latency, and cost.
- Drift monitoring for agent behavior over time.
- A local, privacy-preserving RAG investigation assistant.
- A policy-as-code experiment.

Do not claim the platform is a fully autonomous remediation system. The MVP should recommend actions and require a human to approve changes.

---

## 6. Frontend: required pages

The interface should feel like an **AI testing and analytics workbench**, not only a SOC console.

1. **Overview:** total runs, task success, p95 latency, token use, anomaly count, security findings, pipeline status.
2. **Testing Lab:** configure workload, concurrency, duration, failure injection, agent/version, and run benchmark.
3. **Run Explorer:** search/filter runs; open trace waterfall and inspect model calls, retrievals, tool calls, retries, and failures.
4. **Performance Analytics:** latency distributions, throughput, cost/token metrics, tool performance, time trends.
5. **Quality & RAG Evaluation:** task success, structured output checks, retrieval metrics, groundedness scores, version comparisons.
6. **Anomaly Center:** detector outputs, score/severity, explanation, evidence, acknowledge/mark-noisy controls.
7. **Security & Governance:** policy findings, disallowed tool calls, synthetic sensitive-data events, trace evidence, policy configuration.
8. **SQL Analytics:** curated query gallery, parameter controls, results tables/charts, query execution duration, and links to SQL showcase.
9. **Agent Comparison:** compare two or more agent/model/prompt versions across quality, latency, token use, estimated cost, anomalies, and security outcomes.
10. **AI Investigation Assistant:** ask questions about selected runs and get evidence-linked answers.
11. **Pipeline Health:** Kafka ingestion, Spark processing lag, processed-event counts, errors, Airflow DAG status, lakehouse row counts, and Trino query latency.
12. **Reports:** export a benchmark/regression report to CSV or PDF if feasible.

Use clear empty states, loading/error states, filters, time ranges, pagination, and responsive layouts. Avoid fake metrics: all dashboard values should come from the backend or be clearly labelled as demo seed data.

---

## 7. API requirements

Use FastAPI with typed request/response models, input validation, consistent error formats, and API documentation.

Suggested endpoints:
- `GET /health`
- `GET /api/v1/overview`
- `POST /api/v1/test-runs`
- `GET /api/v1/test-runs`
- `GET /api/v1/test-runs/{run_id}`
- `POST /api/v1/test-runs/{run_id}/stop`
- `GET /api/v1/traces/{trace_id}`
- `GET /api/v1/agents`
- `POST /api/v1/agents`
- `GET /api/v1/analytics/performance`
- `GET /api/v1/analytics/quality`
- `GET /api/v1/analytics/regressions`
- `GET /api/v1/analytics/sql-showcase`
- `GET /api/v1/anomalies`
- `POST /api/v1/anomalies/{alert_id}/feedback`
- `GET /api/v1/security/findings`
- `GET /api/v1/pipeline/health`
- `POST /api/v1/investigations`
- `GET /api/v1/reports/{run_id}`

Use a safe query catalog for the UI. Do not expose arbitrary SQL execution to unauthenticated users. If a read-only SQL console is implemented, enforce SELECT-only statements, restrict catalogs/schemas, apply query timeouts/row limits, and do not concatenate untrusted strings into SQL.

---

## 8. Repository structure

Create a clean repository with clear ownership boundaries. Adapt names as implementation evolves, but preserve separation between services.

```text
agentshield/
├── README.md
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_DICTIONARY.md
│   ├── SQL_SHOWCASE.md
│   ├── BENCHMARK_METHODOLOGY.md
│   ├── THREAT_MODEL.md
│   ├── API.md
│   └── DEMO_SCRIPT.md
├── generator/
│   ├── agents/
│   ├── scenarios/
│   ├── event_schema.py
│   └── producer.py
├── ingestion/
│   ├── kafka_topics.md
│   └── validation.py
├── streaming/
│   ├── spark_job.py
│   ├── feature_engineering.py
│   └── window_aggregations.py
├── lakehouse/
│   ├── table_ddl/
│   └── sample_data/
├── sql/
│   ├── 01_schema_and_tables.sql
│   ├── 02_performance_analytics.sql
│   ├── 03_window_functions_and_rankings.sql
│   ├── 04_regression_comparison.sql
│   ├── 05_security_correlation.sql
│   ├── 06_data_quality_checks.sql
│   ├── 07_summary_tables.sql
│   └── 08_query_plan_experiments.sql
├── ml/
│   ├── train_anomaly_model.py
│   ├── score_events.py
│   └── evaluate_detector.py
├── evaluation/
│   ├── task_evaluator.py
│   ├── rag_metrics.py
│   └── regression_gate.py
├── orchestration/
│   └── dags/
├── investigation/
│   ├── retrieval.py
│   ├── answer_service.py
│   └── knowledge_base/
├── backend/
│   ├── app/
│   └── tests/
├── frontend/
├── scripts/
│   ├── setup.sh
│   ├── generate_demo_data.sh
│   ├── run_benchmark.sh
│   └── reset_demo.sh
└── tests/
    ├── unit/
    ├── integration/
    └── performance/
```

---

## 9. Benchmark and academic evaluation plan

A Big Data project must demonstrate volume, processing, analytical querying, and measured results—not only UI screenshots.

### 9.1 Event volume targets

Build a configurable generator and benchmark progressively:
- 100,000 events for functional verification.
- 1 million events for the first end-to-end benchmark.
- 5 million events as the target demonstration workload.
- 10 million events only if the team machine and schedule allow it.

Report actual successful runs, not only intended targets. Use synthetic events and fixed random seeds for repeatability. Record machine CPU/RAM, Docker resource limits, event schema, workload distribution, and software versions.

### 9.2 Measurements to collect

- Event generation rate.
- Kafka producer throughput and consumer lag.
- Spark processing throughput and end-to-end event delay.
- Invalid/dropped event count.
- Iceberg table size and Parquet storage footprint.
- Trino query latency for raw versus summary-table queries.
- p50/p95/p99 agent latency.
- Task success and evaluation scores.
- Anomaly precision/recall/F1 on labelled synthetic anomaly scenarios where feasible.
- Security-rule detection rate and false positives on the controlled test suite.
- Resource utilization and repeatability.

Do not fabricate benchmark results. Add a script that writes real results to CSV/JSON and a report template that fills in measured values.

### 9.3 SQL performance experiment

Compare a set of representative queries over:
1. Raw or minimally curated events.
2. Curated Iceberg tables with useful partitioning.
3. Pre-aggregated hourly/daily summary tables.

Record query latency and explain the reason for differences. Do not promise a speedup in advance; small local datasets may not show one. Include `EXPLAIN` output and discuss partition pruning, columnar projection, aggregation, and the trade-off between precomputation and freshness.

### 9.4 Academic deliverables

- Architecture diagram and event-flow diagram.
- ER/data model and data dictionary.
- SQL showcase with joins, CTEs, window functions, aggregates, data-quality checks, and query plans.
- Benchmark report with reproducible methodology.
- ML detector evaluation report.
- Threat model and security test scenarios.
- API documentation.
- Final report, presentation, demo script, and screenshots.
- Known limitations and future work.

---

## 10. Airflow pipeline ideas

Implement 2–4 working DAGs rather than many empty DAGs.

1. `daily_agent_regression`: run or load the benchmark suite, compare against the previous baseline, and publish regression results.
2. `nightly_evaluation`: evaluate stored runs and update quality summary tables.
3. `anomaly_model_refresh`: train/evaluate a detector on labelled synthetic data and save model version/metrics.
4. `lakehouse_maintenance`: run data-quality checks and, where supported, compact/maintain Iceberg tables.

DAGs should have meaningful task dependencies, retries, logs, and failure handling. If full orchestration is too expensive to debug, keep one fully working DAG and document the other planned workflows.

---

## 11. Four-person team split

Suggested ownership:
- **Member 1 — Big Data pipeline:** Kafka, Spark Structured Streaming, event schema, stream features, throughput measurements.
- **Member 2 — Lakehouse and SQL:** Iceberg, MinIO, Trino, table design, SQL analytics, query-plan/performance experiments.
- **Member 3 — AI evaluation and detection:** benchmark scenarios, quality/RAG metrics, anomaly detector, security rules, evaluation report.
- **Member 4 — Product integration:** FastAPI, React dashboard, trace explorer, investigation assistant, demo/report integration.

All members should understand the end-to-end architecture. Define shared event contracts and API schemas early; do not allow separate modules to invent incompatible identifiers or field names.

---

## 12. 45-day execution plan

### Days 1–5: Design and local environment
- Finalize architecture, schema, topic names, event IDs, and API contracts.
- Set up repository, Docker Compose, formatting, tests, and `.env.example`.
- Bring up the minimum services and verify health checks.
- Deliverable: architecture diagram and a working environment.

### Days 6–12: Event generation and ingestion
- Build synthetic agent scenarios and structured telemetry.
- Publish and consume Kafka events.
- Add validation, timestamps, run/trace/span relationships, and error handling.
- Deliverable: reproducible end-to-end event stream.

### Days 13–19: Spark and lakehouse
- Implement Spark Structured Streaming transformations and time-window aggregates.
- Write raw/curated data to Iceberg/Parquet on MinIO.
- Configure Trino to query the tables.
- Deliverable: real events flowing from Kafka into SQL-queryable lakehouse tables.

### Days 20–25: SQL and performance testing
- Implement the required SQL showcase.
- Add run orchestration, benchmark workloads, and metrics capture.
- Compare versions and calculate percentiles and throughput.
- Deliverable: benchmark results plus query outputs.

### Days 26–31: Evaluation and anomaly/security detection
- Add deterministic task evaluators, RAG metrics, rule-based detections, and Isolation Forest.
- Label synthetic anomaly scenarios and evaluate detection quality.
- Deliverable: evidence-backed anomaly and security findings.

### Days 32–37: Backend and dashboard
- Finish FastAPI endpoints and connect the frontend to real data.
- Build testing lab, performance analytics, run explorer, SQL analytics, and finding pages.
- Deliverable: integrated dashboard with no fabricated live metrics.

### Days 38–41: Investigation assistant and orchestration
- Add evidence-grounded RAG investigation, if core modules are stable.
- Implement at least one useful Airflow DAG and pipeline-health view.
- Deliverable: trace-grounded explanations and scheduled evaluation.

### Days 42–45: Integration, benchmarks, and presentation
- Run 1M and target event-volume benchmarks.
- Fix high-impact bugs, test fresh setup instructions, and record measurements.
- Prepare SQL showcase, architecture diagram, demo script, report, and slides.
- Deliverable: reproducible project demo and evidence-based academic report.

**Scope rule:** If behind schedule, prioritize a fully working Kafka → Spark → Iceberg/MinIO → Trino path, real SQL analytics, a benchmark runner, and at least one validated anomaly detector. Keep optional LLM calls and elaborate UI features out of the critical path.

---

## 13. Testing and acceptance criteria

The project is not complete until these checks pass:

- A clean setup from README instructions works on a fresh environment as far as the documented machine prerequisites allow.
- A test run emits events with stable run/trace/span IDs.
- Kafka receives events and the Spark job processes them without silently losing invalid records.
- Curated Iceberg tables are queryable through Trino.
- The SQL showcase queries execute against the real schema.
- At least one benchmark run generates measured throughput and latency results.
- The dashboard uses backend data and handles service errors gracefully.
- Known synthetic anomaly cases trigger the intended detector/rule; normal cases are also tested.
- Security findings show the policy rule and supporting trace evidence.
- The RAG assistant, if enabled, cites available evidence and declines to guess when evidence is absent.
- Unit and integration tests cover schema validation, evaluators, anomaly logic, and API behavior.
- The final report distinguishes implemented features, optional features, measured results, and limitations.

---

## 14. Engineering and safety requirements

- Use `.env` for secrets; commit only `.env.example`.
- Do not hardcode API keys or expose them in frontend code.
- Use synthetic user data and synthetic canary secrets.
- Keep mock tools sandboxed and allowlisted. Do not give the agent unrestricted shell or filesystem access.
- Treat prompts, retrieved documents, and event payloads as untrusted input.
- Redact sensitive content in logs by default.
- Use parameterized queries and input validation.
- Mark estimated costs and model-judged scores clearly.
- Keep all remediation recommendations human-approved.
- Add structured logs, timeouts, retries, and clear service-health status.
- Pin versions where feasible and document compatibility issues.

---

## 15. Reference material

Use these sources as implementation guidance; check the version-specific documentation when selecting dependencies.

1. OpenTelemetry, *AI Agent Observability — Evolving Standards and Best Practices*: https://opentelemetry.io/blog/2025/ai-agent-observability/
2. OpenTelemetry, *Inside the LLM Call: GenAI Observability with OpenTelemetry* (2026): https://opentelemetry.io/blog/2026/genai-observability/
3. OpenTelemetry GenAI metrics conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/
4. Apache Iceberg, Spark Structured Streaming: https://iceberg.apache.org/docs/latest/spark-structured-streaming/
5. Trino, Iceberg connector: https://trino.io/docs/current/connector/iceberg.html
6. Trino lakehouse ecosystem: https://trino.io/ecosystem/data-lake.html
7. Microsoft Learn, observability for generative AI and agentic AI systems: https://learn.microsoft.com/en-us/security/zero-trust/sfi/observability-ai-systems

The project should use these references to inform design, not copy claims or imply that AgentShield implements every capability discussed in them.

---

# 16. Instructions for Claude Code

You are the lead engineer implementing AgentShield from this specification. Build a working, integrated application—not just mockups, pseudocode, or disconnected sample files.

## Mandatory workflow

1. Inspect the repository before changing files. Preserve useful existing work.
2. Create a concise implementation plan and identify compatibility risks.
3. Build in vertical slices, keeping the application runnable after each slice.
4. Implement the shared event schema and contracts before separate modules.
5. Pin compatible dependencies and use Docker Compose health checks and persistent volumes where appropriate.
6. Add automated tests and run them after each major change.
7. Maintain `README.md`, `.env.example`, architecture documentation, SQL scripts, and demo instructions as the implementation changes.
8. Use actual API/backend/lakehouse data in the dashboard. Clearly label any seeded demo data.
9. If a service is not available locally, provide a transparent degraded mode and a clear setup explanation; do not silently pretend the service is working.
10. Never fabricate benchmark results. Build repeatable scripts to measure them.
11. Prioritize the end-to-end Big Data path and SQL showcase before optional LLM integrations or visual polish.
12. At the end of each implementation phase, report files changed, commands run, test outcomes, blockers, and the next phase.

## Implementation phases

**Phase A — Contracts and skeleton**
- Establish repository layout, shared event schema, environment configuration, Compose services, health checks, and a smoke test.

**Phase B — End-to-end Big Data path**
- Generate synthetic events → publish to Kafka → process with Spark → store in Iceberg/Parquet on MinIO → query through Trino.
- Prove the path with a small script and documented query.

**Phase C — SQL analytics**
- Implement the SQL showcase and real API endpoints for performance, comparison, and data-quality results.

**Phase D — Testing and evaluation**
- Build test-run controls, scenario runner, deterministic evaluator, benchmark capture, and regression comparisons.

**Phase E — Anomaly and security**
- Implement baseline/rule detections, Isolation Forest, policy checks, labelled synthetic scenarios, and detector evaluation.

**Phase F — Frontend integration**
- Implement the testing lab, trace explorer, analytics, SQL showcase, anomalies, security findings, and pipeline health pages.

**Phase G — AI investigation and orchestration**
- Add RAG-backed investigation with evidence citations and Airflow DAGs after the core is stable.

**Phase H — Benchmark and deliver**
- Run reproducible volume tests, export results, fix integration issues, and complete academic documentation.

## Claude Code output expectations

- Do not stop after writing a plan; proceed to implementation.
- Do not replace the whole architecture with a simpler unrelated stack without explaining a real blocker.
- Do not create a giant monolith when services have distinct responsibilities.
- Keep the local demo manageable; do not add Kubernetes or a cloud deployment requirement.
- Add commands for setup, start, stop, reset, tests, data generation, and benchmark runs.
- Provide sample SQL outputs and explain the analytical meaning.
- Ensure the app has a coherent, professional, responsive UI.
- When a choice is uncertain, favor the simplest maintainable implementation that proves the Big Data architecture and satisfies the acceptance criteria.
