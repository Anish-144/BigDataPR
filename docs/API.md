# API reference

Generated from the running API's OpenAPI document (AgentShield API 0.1.0). Interactive docs: http://localhost:8000/docs.

## Conventions

- JSON everywhere; errors are `{"error": {...}}` (validation, 500) or `{"detail": {"code", "message"}}` (domain errors).
- 422 = invalid input (validated before any query runs); 404 = unknown id; 409 = conflict (e.g. a test run is already active); 503 = a dependency (Trino/lakehouse, Postgres) is unavailable.
- No endpoint executes caller-supplied SQL. Analytics use fixed queries or the curated read-only catalog with typed, prepared-statement parameters; Trino enforces a query timeout and the API limits rows.
- Costs are estimates (config/pricing.yaml); agent latency/tokens are simulated by mock agents.

## Endpoints

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/agents` | List Agents |
| POST | `/api/v1/agents` | Register an agent version in the operational registry (Postgres). Config agents are read-only. |
| GET | `/api/v1/analytics/comparison` | Side-by-side comparison of 2-6 agent versions across quality, latency, cost, anomalies and security. |
| GET | `/api/v1/analytics/data-quality` | Data-quality checks run incrementally over recent partitions. Exact distinct counts and anti-joins over the |
| GET | `/api/v1/analytics/performance` | Performance |
| GET | `/api/v1/analytics/quality` | Quality |
| GET | `/api/v1/analytics/regressions` | Regressions |
| GET | `/api/v1/analytics/sql-showcase` | The curated, read-only query gallery (SQL text + analytical question + interpretation). |
| POST | `/api/v1/analytics/sql-showcase/{name}/run` | Execute one catalog query with validated, prepared-statement parameters. |
| POST | `/api/v1/analytics/summary-tables/refresh` | Rebuild hourly/daily summary partitions for the last N days (sql/07_summary_tables.sql DML). |
| GET | `/api/v1/anomalies` | List Alerts |
| POST | `/api/v1/anomalies/score` | Run the rule + Isolation Forest detectors over a test run (or recent runs) and publish alerts via Kafka. |
| GET | `/api/v1/anomalies/summary` | Summary |
| GET | `/api/v1/anomalies/{alert_id}` | Get Alert |
| POST | `/api/v1/anomalies/{alert_id}/feedback` | Record whether an alert was useful or noisy (kept for detector review; never auto-applied). |
| POST | `/api/v1/investigations` | Answer an investigation question from lakehouse evidence and local runbooks. |
| GET | `/api/v1/investigations/examples` | Examples |
| GET | `/api/v1/investigations/history` | History |
| GET | `/api/v1/ml/detector-evaluation` | Detector Evaluation |
| GET | `/api/v1/overview` | Headline KPIs computed live from the lakehouse. |
| GET | `/api/v1/pipeline/health` | Measured status of Kafka, Spark, Trino/lakehouse, PostgreSQL and (optional) Airflow. |
| POST | `/api/v1/regression-gate` | Compare candidate vs baseline cohorts against config/thresholds.yaml; result is stored in the lakehouse. |
| GET | `/api/v1/regression-gate/results` | Gate Results |
| GET | `/api/v1/reports/{test_run_id}` | Report |
| GET | `/api/v1/runs` | Search agent runs with filters and pagination. Every filter is a bound parameter. |
| GET | `/api/v1/runs/{run_id}` | Get Run |
| GET | `/api/v1/scenarios` | List Scenarios |
| GET | `/api/v1/security/findings` | Findings |
| GET | `/api/v1/security/policy` | The active policy-as-code configuration (config/policies.yaml). |
| GET | `/api/v1/security/summary` | Summary |
| POST | `/api/v1/test-runs` | Start a test run (same engine as the CLI) in the background; telemetry flows through Kafka. |
| GET | `/api/v1/test-runs` | Test runs from the lakehouse (all, incl. CLI) merged with live API-run status from PostgreSQL. |
| GET | `/api/v1/test-runs/{test_run_id}` | Get Test Run |
| POST | `/api/v1/test-runs/{test_run_id}/stop` | Stop Test Run |
| GET | `/api/v1/traces/{trace_id}` | Full trace: spans (waterfall), run summary, evaluations, security findings and anomaly alerts. |
| GET | `/health` | Liveness of the API process itself (dependencies: see /api/v1/pipeline/health). |

## Parameters per endpoint

### POST /api/v1/agents
- JSON body: `AgentIn`

### GET /api/v1/analytics/comparison
- `days` (query) maximum=3650, minimum=1, default=30
- `versions` (query, required) pattern=^[a-z0-9\-]+@[0-9.]+(,[a-z0-9\-]+@[0-9.]+){1,5}$

### GET /api/v1/analytics/data-quality
- `days` (query) maximum=3650, minimum=1, default=30

### GET /api/v1/analytics/performance
- `days` (query) maximum=3650, minimum=1, default=30

### GET /api/v1/analytics/quality
- `days` (query) maximum=3650, minimum=1, default=30

### GET /api/v1/analytics/regressions
- `days` (query) maximum=3650, minimum=1, default=30
- `scenario` (query) pattern=^[A-Za-z0-9_\-]{1,64}$, default=regression

### POST /api/v1/analytics/sql-showcase/{name}/run
- `name` (path, required) 
- JSON body: `object`

### POST /api/v1/analytics/summary-tables/refresh
- `days` (query) maximum=3650, minimum=1, default=60

### GET /api/v1/anomalies
- `days` (query) maximum=3650, minimum=1, default=30
- `severity` (query) 
- `anomaly_type` (query) 
- `detector` (query) 
- `agent_id` (query) 
- `test_run_id` (query) 
- `limit` (query) maximum=500, minimum=1, default=50
- `offset` (query) maximum=100000, minimum=0, default=0

### POST /api/v1/anomalies/score
- JSON body: `ScoreRequest`

### GET /api/v1/anomalies/summary
- `days` (query) maximum=3650, minimum=1, default=30

### GET /api/v1/anomalies/{alert_id}
- `alert_id` (path, required) pattern=^A-[0-9a-f]{16}$

### POST /api/v1/anomalies/{alert_id}/feedback
- `alert_id` (path, required) pattern=^A-[0-9a-f]{16}$
- JSON body: `Feedback`

### POST /api/v1/investigations
- JSON body: `InvestigationIn`

### GET /api/v1/investigations/history
- `limit` (query) maximum=200, minimum=1, default=20

### GET /api/v1/overview
- `days` (query) maximum=3650, minimum=1, default=30

### POST /api/v1/regression-gate
- JSON body: `GateRequest`

### GET /api/v1/regression-gate/results
- `limit` (query) maximum=200, minimum=1, default=20

### GET /api/v1/reports/{test_run_id}
- `test_run_id` (path, required) pattern=^TR-\d{8}-[0-9a-f]{6}$
- `format` (query) enum=['json', 'csv', 'md', 'html'], default=json

### GET /api/v1/runs
- `days` (query) maximum=3650, minimum=1, default=30
- `agent_id` (query) 
- `agent_version` (query) 
- `test_run_id` (query) 
- `status` (query) 
- `success` (query) 
- `has_findings` (query) 
- `min_latency_ms` (query) 
- `run_id` (query) 
- `sort` (query) enum=['recent', 'slowest', 'most_tokens'], default=recent
- `limit` (query) maximum=500, minimum=1, default=50
- `offset` (query) maximum=100000, minimum=0, default=0

### GET /api/v1/runs/{run_id}
- `run_id` (path, required) pattern=^[A-Za-z0-9_\-]{1,80}$

### GET /api/v1/security/findings
- `days` (query) maximum=3650, minimum=1, default=30
- `severity` (query) 
- `rule_id` (query) 
- `category` (query) 
- `action` (query) 
- `agent_id` (query) 
- `test_run_id` (query) 
- `limit` (query) maximum=500, minimum=1, default=50
- `offset` (query) maximum=100000, minimum=0, default=0

### GET /api/v1/security/summary
- `days` (query) maximum=3650, minimum=1, default=30

### POST /api/v1/test-runs
- JSON body: `TestRunRequest`

### GET /api/v1/test-runs
- `limit` (query) maximum=500, minimum=1, default=50

### GET /api/v1/test-runs/{test_run_id}
- `test_run_id` (path, required) pattern=^TR-\d{8}-[0-9a-f]{6}$

### POST /api/v1/test-runs/{test_run_id}/stop
- `test_run_id` (path, required) pattern=^TR-\d{8}-[0-9a-f]{6}$

### GET /api/v1/traces/{trace_id}
- `trace_id` (path, required) pattern=^[0-9a-f]{32}$
