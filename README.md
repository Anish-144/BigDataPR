# AgentShield

A Big Data platform for AI-agent performance benchmarking, reliability evaluation, anomaly detection and
security governance. Deterministic synthetic agent workloads emit OpenTelemetry-style telemetry that flows
**Kafka → Spark Structured Streaming → Apache Iceberg (Parquet on MinIO) → Trino SQL**. A FastAPI backend, a
React workbench, ML detectors, a regression gate, an evidence-grounded investigation assistant and Airflow DAGs
are built on top.

Specification: [AgentShield_Revised_Master_Project_Prompt.md](AgentShield_Revised_Master_Project_Prompt.md).
Project report: [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md).

## Status

| Phase | Scope | Status |
|---|---|---|
| A | Event contract, repo layout, Compose stack, health checks | Done |
| B | Generator → Kafka → Spark → Iceberg/MinIO → Trino, proven by integration tests | Done |
| C | SQL showcase (`sql/01`–`09`, 51 queries), summary tables, SQL benchmark, analytics API | Done |
| D | Test-run API, regression gate, 1M/5M pipeline benchmarks | Done |
| E | Rules + Isolation Forest anomaly detection, holdout evaluation, policy/security analytics | Done |
| F | React dashboard (12 pages + trace waterfall) | Done |
| G | Investigation assistant (retrieval + fixed queries; optional LLM), 3 Airflow DAGs | Done |
| H | Measured benchmarks, generated docs, demo script | In progress: docs and demo script written; final clean-data rebuild with 1M/5M benchmarks pending (`scripts/rebuild_full_dataset.sh --yes`) |

Implemented, optional and missing items are listed one by one in [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md).

## Headline measured results

<!-- RESULTS:START -->
Final numbers will be filled in after the clean rebuild. Measurements taken so far (before the rebuild) are in `benchmarks/results/archive/` and summarized in [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md): a 1,009,825-event run fully landed in the lakehouse 86 s after production started (producer 51.6k events/s, Spark ~12.5k rows/s, quarantined records exactly equal to injected ground truth). On the held-out anomaly scenario, rules reached precision 1.0 / recall 0.63 and the combined detectors F1 0.78 at a 0.78% false-positive rate. Measured on one machine (24 logical CPUs, Docker with 7.6 GiB).
<!-- RESULTS:END -->

## Architecture

```
generator (Python, N processes, fixed seeds) ─► Kafka (6 topics) ─► Spark Structured Streaming (2 queries)
   ─► Iceberg tables (Parquet/ZSTD on MinIO, JDBC catalog in PostgreSQL) ─► Trino ─► FastAPI ─► React (nginx)
detectors (rules + Isolation Forest) read Trino and publish alerts back to Kafka; Airflow schedules the batch work
```

Details, versions and design decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Prerequisites

- Docker Desktop with about 7.5 GiB for Docker. The optional Airflow profile needs about 1.5 GiB more, so
  raise the WSL/Docker memory limit or stop Airflow during benchmarks.
- Python 3.12 for host tools and tests. The services run in Docker.
- Windows: run `scripts/*.sh` from Git Bash.
- Host ports used: 3000, 8000, 8080, 4040, 9000/9001, 9094, 5433 (Postgres), 8088 (Airflow). All are bound to
  127.0.0.1.

## Quick start

```bash
scripts/setup.sh                     # venv + pinned deps, build images, start the stack
scripts/generate_demo_data.sh        # ~0.7M events from 4 seeded scenarios (~5 min)
# open http://localhost:3000
```

## Commands

Commands below use `.venv/Scripts/python` (Windows). On macOS/Linux use `.venv/bin/python`.

```bash
# stack
docker compose up -d                                   # core stack + dashboard
docker compose --profile orchestration up -d airflow   # + Airflow (DAGs start paused)
docker compose stop                                    # stop, keep data
docker compose down -v                                 # DESTRUCTIVE: remove containers and data volumes
scripts/reset_demo.sh --yes                            # DESTRUCTIVE: wipe events/tables/checkpoints, keep services
scripts/rebuild_full_dataset.sh --yes                  # DESTRUCTIVE: rebuild data + every measured result (~40 min)

# workloads (generator/scenarios/*.yaml)
.venv/Scripts/python -m generator.producer --scenario generator/scenarios/smoke.yaml
.venv/Scripts/python -m generator.producer --scenario generator/scenarios/live_demo.yaml      # realtime, throttled
.venv/Scripts/python -m generator.producer --scenario generator/scenarios/benchmark.yaml --tasks 70000 --workers 6

# SQL
.venv/Scripts/python -m lakehouse.run_sql sql/02_performance_analytics.sql
.venv/Scripts/python -m lakehouse.run_sql "sql/0[2-9]*.sql" --export docs/sql_outputs
.venv/Scripts/python -m lakehouse.run_sql sql/07_summary_tables.sql                          # refresh summaries
.venv/Scripts/python -m lakehouse.maintenance compact --days 2                               # Iceberg compaction

# evaluation, detection, security
.venv/Scripts/python -m evaluation.regression_gate --all --scenario regression
.venv/Scripts/python -m ml.train_anomaly_model --scenarios baseline regression
.venv/Scripts/python -m ml.evaluate_detector --eval-scenario fault_injection_holdout
.venv/Scripts/python -m ml.score_events --since-minutes 60                                   # publish alerts via Kafka

# benchmarks (results -> benchmarks/results/, report -> docs/BENCHMARK_REPORT.md)
scripts/run_benchmark.sh 1000000
.venv/Scripts/python -m benchmarks.sql_benchmark --runs 5
.venv/Scripts/python -m docs.generate_docs              # data dictionary, SQL showcase, API, benchmark report

# tests
.venv/Scripts/python -m pytest                                   # unit, contract, API (no Docker needed)
.venv/Scripts/python -m pytest -m integration tests/integration  # end-to-end against the running stack
cd frontend && npm install && npm run build                      # dashboard type-check + build
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API + OpenAPI docs | http://localhost:8000/docs |
| Trino UI | http://localhost:8080 |
| Spark UI (Structured Streaming) | http://localhost:4040 |
| MinIO console | http://localhost:9001 (credentials in `.env`) |
| Airflow (optional) | http://localhost:8088 (admin / `AIRFLOW_ADMIN_PASSWORD`, default `admin`) |

## Documentation

| Document | Content |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, event contract, design decisions, compatibility notes |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every table and column, generated from the live schema |
| [docs/SQL_SHOWCASE.md](docs/SQL_SHOWCASE.md) | 51 queries: question, concept, SQL, real output, interpretation |
| [docs/BENCHMARK_METHODOLOGY.md](docs/BENCHMARK_METHODOLOGY.md) | Workloads, metric definitions, fairness rules |
| [docs/BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md) | All measured results, generated from `benchmarks/results/` |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | Threats, controls, security test scenarios, detector iteration log |
| [docs/API.md](docs/API.md) | Endpoints and parameters, generated from OpenAPI |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 15-20 minute presentation walkthrough |
| [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md) | Spec coverage, decisions, limitations, team split |

## Optional LLM features

The platform works without any model API. To let the investigation assistant rephrase its (already grounded)
answers, and to enable the optional groundedness judge (`llm_judge_rate` in a scenario), set the following in `.env`:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-opus-5-5
```

Requests opt into Anthropic's server-side refusal fallback. On any error or refusal the deterministic answer is used.

## Limitations

- **Single machine.** One Kafka broker, Spark `local[4]`, one Trino node. No distributed scaling is claimed.
- **Simulated agent latency and tokens.** Mock agents simulate them. Pipeline, storage and query measurements
  are real.
- **No authentication, TLS or encryption at rest.** This is a local demo, and ports are bound to 127.0.0.1.
- **Heuristic security rules.** Some fault types are weakly detected; see the detector results.

## Troubleshooting

- **Port 5432 in use:** the Docker Postgres already uses host port 5433 (`POSTGRES_HOST_PORT`).
- **Spark is slow to catch up after a burst:** this is expected. Pipeline Health shows consumer lag, and Spark
  processes about 12k rows/s.
- **Trino errors with `EXCEEDED_LOCAL_MEMORY_LIMIT`:** a single query hit the 512 MB per-query limit
  (`infra/trino/etc/config.properties`). This limit protects the server from crashing.
- **Git Bash path errors in scripts:** the scripts set `MSYS_NO_PATHCONV=1`. Keep that setting if you write new ones.
