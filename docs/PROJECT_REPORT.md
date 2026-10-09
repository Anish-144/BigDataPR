# AgentShield - project report

**AgentShield: A Big Data Platform for AI Agent Performance Benchmarking, Reliability Evaluation, Anomaly
Detection, and Security Governance**

## Abstract

Autonomous AI agents combine language models, retrieval, memory and tools. This creates long execution paths that
conventional application metrics cannot explain. AgentShield captures agent execution telemetry as
OpenTelemetry-style traces and processes it through a streaming lakehouse: Apache Kafka, Apache Spark Structured
Streaming, Apache Iceberg tables stored as Parquet on MinIO, and Trino SQL. On top of the lakehouse it:
- measures performance, estimated cost and reliability;
- evaluates task quality and RAG retrieval with deterministic metrics;
- gates releases with a statistical regression gate;
- detects anomalous executions with explainable rules and an Isolation Forest;
- surfaces security and governance findings from a policy-as-code engine;
- answers investigation questions with evidence-grounded responses.

Repeatable synthetic workloads with fixed seeds drive every result. Throughput, latency, query performance and
detection quality are measured on a single machine and reported as measured (docs/BENCHMARK_REPORT.md).

## 1. Implementation status against the specification

Legend: **Done** = implemented and tested; **Optional (done)** = optional spec item implemented; **Partial** = works
with documented gaps; **Not done** = not implemented.

| Spec area | Status | Evidence |
|---|---|---|
| 2.1 Testing lab: QA, RAG, tool-using, multi-step agents; failure injection; configurable scenarios | Done | `generator/`, 8 scenario files, API `POST /test-runs`, Testing Lab page |
| 2.1 No paid API required; optional real LLM adapter | Done | Deterministic mock agents; `common/llm.py` (off unless `LLM_PROVIDER=anthropic`) |
| 2.2 Performance metrics (success, p50/p90/p95/p99, TTFT, throughput, tokens, cost, tools, errors, worker CPU/memory, stream lag, Trino query stats) | Done | sql/02, `worker_resource_metrics`, `pipeline_batch_metrics`, Pipeline Health |
| 2.2 No invented costs | Done | `config/pricing.yaml` labelled illustrative; `cost_source` on every row |
| 2.3 Deterministic evaluation (completion, schema validity, tool selection/args, Recall@K, Precision@K, MRR, citation coverage, groundedness, hallucination indicator) | Done | `evaluation/task_evaluator.py`, `evaluation/rag_metrics.py` |
| 2.3 Regression comparison | Done | `evaluation/regression_gate.py`, sql/04, API, Airflow DAG |
| 2.3 / 5.3 LLM-as-a-judge, labelled separately | Optional (done) | `evaluation/llm_judge.py`, `evaluator_type = model_judge`; untested against a live API (no key available) |
| 2.4 Rule-based + ML anomaly detection; alerts with severity, score, window, ids, metrics, explanation; feedback | Done | `ml/`, Anomaly Center, `POST /anomalies/{id}/feedback` |
| 2.4 Drift / rolling baseline by version | Partial | Per-version robust baselines and window tests; no long-term drift tracking |
| 2.5 Security analytics (allowlist, restricted data, injection, canary, privilege, exfiltration, policy) | Done | `security/`, `config/policies.yaml`, sql/05 |
| 2.6 Investigation assistant with evidence, declines without evidence, no arbitrary SQL | Done | `investigation/`; TF-IDF retrieval by default; Sentence Transformers + FAISS optional (not installed by default) |
| 3.3 Kafka topics, stable ids, DLQ | Done | 6 topics; `agent-events-dlq`; Spark quarantine table |
| 3.4 Lakehouse tables, partitioning, schema evolution, time travel / rollback | Done | sql/01, sql/09, `lakehouse/` |
| 4 SQL showcase 01-08 + SQL_SHOWCASE.md with real outputs | Done | `sql/` (plus 09), docs/SQL_SHOWCASE.md generated from exports |
| 5.1 OpenTelemetry-inspired traces; no raw prompts by default | Done | Span model; `CAPTURE_CONTENT=false` default with redaction |
| 6 Frontend: 12 pages | Done | `frontend/` (React + Vite + TS + Tailwind), served by nginx at :3000 |
| 7 API endpoints | Done | 34 paths; docs/API.md generated from OpenAPI |
| 9 Benchmarks 100k / 1M / 5M with methodology | Done | `benchmarks/`, docs/BENCHMARK_METHODOLOGY.md, BENCHMARK_REPORT.md |
| 9 10M events | Not done | Machine/schedule budget; not claimed |
| 10 Airflow DAGs (2-4 working) | Done | 3 DAGs, executed successfully end to end |
| 13 Unit + integration tests | Done | `pytest` (unit, contract, API) and `pytest -m integration` (live stack) |
| 14 Safety: .env, pinned versions, parameterised queries, redaction, human-approved remediation | Done | See docs/THREAT_MODEL.md |
| Authentication / RBAC | Not done | Local demo; ports bound to 127.0.0.1 |

## 2. Engineering decisions worth discussing

The project log records each problem with its measurement and its fix (docs/ARCHITECTURE.md section 8, and
THREAT_MODEL.md):

1. **Contract-first design.** Pydantic models are the single source of truth. Contract tests make the Spark DDL
   and Trino tables fail CI if they drift.
2. **Nothing silently lost.** The bronze table stores every record. Quarantine reasons were reconciled exactly
   against injected corruption in integration tests and in every benchmark.
3. **Effectively-once ingestion.** Snapshot-tagged commits skip already-committed tables on replay. Measured
   result: 0 duplicated Kafka offsets after several restarts.
4. **Data quality caught real bugs.** The DQ checks surfaced several of the problems below:
   - **Reset bug (Windows).** A path-conversion bug left old Kafka data in place after a reset, which showed up
     as 35% duplicate events.
   - **Reused identifiers.** Repeated test runs with the same seed reused trace IDs (8,537 colliding traces).
     Identifiers are now scoped per test run; outcomes stay reproducible from the seed.
   - **Silently rounded rates.** A DECIMAL-literal pitfall rounded success rates to one decimal place.
5. **Detector rigour.** Model thresholds are chosen without labels. Design iterations used a dev scenario, and
   final numbers come from a holdout scenario with a new seed and unseen incident types. Bonferroni correction
   was applied to window tests after measuring false alarms.
6. **Measured, not assumed.** Partition pruning, compaction and sorting were each measured. Results where an
   optimization did *not* reduce latency at this scale are reported as such.

## 3. Results

See docs/BENCHMARK_REPORT.md (generated from `benchmarks/results/`). Headline numbers are in README.md.

## 4. Limitations and future work

- **Single node.** One Kafka broker (replication factor 1), Spark `local[4]`, one Trino node. Next steps:
  multi-node deployment, then a scaling study.
- **Simulated agent latency and tokens.** A real-LLM workload adapter would measure provider latency and TTFT.
- **Heuristic security rules.** They can be evaded by obfuscated injections. Future work: a classifier-based
  detector, evaluated on a public injection dataset.
- **Weak detector coverage for some faults.** Quality-only failures (failed retrieval returning irrelevant
  documents, malformed output) and retry-masked tool outages are weakly detected. Planned v3: a span-level
  tool-error-rate window rule (not applied to the holdout, to avoid contaminating it).
- **No authentication, TLS or encryption at rest.** This is a local single-user demo.
- **Not run:** 10M-event benchmark, Sentence-Transformer retrieval, and a live LLM judge.

## 5. Team ownership (suggested split, spec section 11)

| Member | Owned modules |
|---|---|
| 1 - Big Data pipeline | `generator/event_schema.py`, `generator/producer.py`, `ingestion/`, `streaming/`, Kafka/Spark infra, pipeline benchmark |
| 2 - Lakehouse & SQL | `sql/`, `lakehouse/`, Trino/Iceberg/MinIO infra, summary tables, SQL benchmark, data dictionary |
| 3 - AI evaluation & detection | `generator/agents/`, `evaluation/`, `ml/`, `security/`, scenarios, detector evaluation |
| 4 - Product integration | `backend/`, `frontend/`, `investigation/`, `orchestration/`, demo and reports |
