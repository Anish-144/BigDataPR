# Demo script (15-20 minutes)

Audience: faculty evaluating a Big Data + AI engineering project. The demo follows one story: *a new agent
release looks faster and cheaper - is it safe to ship?* Along the way it shows the streaming lakehouse, SQL
analytics, evaluation, anomaly detection, security and the assistant. Numbers on screen come from the live system.
Do not quote numbers from memory; read them off the screen or from docs/BENCHMARK_REPORT.md.

## 0. Before the session (10 minutes earlier)

```bash
docker compose up -d                                   # core stack + dashboard
docker compose --profile orchestration up -d airflow   # optional: only if you will show Airflow
# Data already loaded? Overview shows ~100k+ runs. If not:
scripts/generate_demo_data.sh                          # ~5 min
```

Open these browser tabs:

| Tab | URL |
|---|---|
| Dashboard | http://localhost:3000 (landing page; open the workbench at http://localhost:3000/app) |
| Spark UI (Structured Streaming tab) | http://localhost:4040 |
| Trino UI | http://localhost:8080 (any user name) |
| MinIO console (bucket `warehouse/analytics`) | http://localhost:9001 |
| Airflow | http://localhost:8088 (admin / admin) |

## 1. Problem and architecture (2 min)

- Agents combine models, retrieval, memory and tools, so failures hide in long execution paths. Application
  metrics alone cannot explain them.
- Show the diagram in docs/ARCHITECTURE.md. One event contract flows through Kafka → Spark Structured Streaming →
  Iceberg/Parquet on MinIO → Trino, and the same telemetry answers performance, quality and security questions.
- Say it plainly: mock agents simulate model latency and tokens. Tool calls, retrieval, policy checks, the
  pipeline and the queries are real. Everything runs on a single machine.

## 2. Live pipeline (3 min)

1. **Testing Lab** → scenario `live_demo` (realtime, throttled) → Start. Point out that the run is queued and
   then running, and that progress updates.
2. **Pipeline Health**: Kafka message counts rise and Spark micro-batches appear with rows, duration and
   consumer lag. Explain the 10 s trigger, and that the window query uses a 30-minute watermark.
3. **Spark UI → Structured Streaming**: the two queries, `lakehouse_fanout` and `window_metrics_1m`.
4. **MinIO console**: Parquet data files and Iceberg `metadata/` under `warehouse/analytics/agent_spans-.../`.
5. Mention data quality. Bad records are quarantined with a reason, and nothing is dropped. The integration tests
   prove quarantine counts equal the injected ground truth.

## 3. One trace end to end (2 min)

1. **Run Explorer** → filter `status = timeout` → open a run.
2. In the **waterfall**, point out the three 8-second tool attempts (retries), the policy-check spans, and the
   timeout ring.
3. **Evaluations** tab: deterministic checks, each with rubric and evidence. Mention that model-judged scores are
   stored separately when enabled.
4. The yellow banner shows the synthetic ground-truth label. Explain that it is never a detector input.

## 4. SQL is a first-class feature (3 min)

**SQL Analytics** shows a gallery of 51 annotated queries from `sql/`.

- `latency_percentiles_by_version`: percentiles; then `exact_vs_approx_p95` to show the approximation error (<1%).
- `rolling_success_rate`: window functions (moving average, LAG).
- `cohort_ab_comparison`: conditional aggregation with FILTER, baseline vs candidate.
- `plan_partition_pruning` / `analyze_with_partition_filter`: EXPLAIN and pruning.
- `security_detection_vs_ground_truth`: UNNEST of labels, a confusion-matrix style query.
- Show docs/BENCHMARK_REPORT.md for the three-tier result: raw JSON vs curated facts vs summary table. Then the
  honest negatives: pruning to one day reads ~29x fewer rows but saves only ~10 ms at this size; sorting alone does not help,
  but sorting with small row groups cuts rows read per trace lookup from ~681k to ~3.8k (about 180x).
- Mention the decimal-literal pitfall (`1.0` vs `1e0`) found during the project. It is good teaching material.

## 5. "Faster and cheaper" - is it better? (2 min)

1. **Agent Comparison** → `rag-helpdesk@2.0.0` vs `rag-helpdesk@2.1.0`. The new version is faster and cheaper per
   request, but Recall@K and task success are lower.
2. **Testing Lab → Regression gate**: rag-helpdesk 2.0.0 → 2.1.0 on scenario `regression`. The verdict is FAILED,
   with the breached checks and the p-value. Stress that the gate recommends and a human decides.
3. **Quality & RAG** shows the per-metric view: Recall@K, MRR, citation coverage, groundedness.

## 6. Anomaly detection with honest evaluation (2 min)

**Anomaly Center**:
- Detector metrics on a **held-out** scenario: rules have high precision; the Isolation Forest adds recall on
  multivariate faults; the combined detectors' F1 is shown.
- Per-fault recall. Point at weak spots openly: malformed-output and failed-retrieval faults, and the missed tool
  outage (retries mask it). Explain the Bonferroni-corrected window tests.
- Open an alert, follow it to its trace, and mark it *useful*. Feedback is stored and never auto-applied.

## 7. Security and governance (2 min)

**Security & Governance**:
- Findings by rule. Open an SEC-007 exfiltration finding to see the restricted read followed by an egress attempt
  that was blocked.
- Policy tab shows policy-as-code: per-agent allowlists and prohibited actions.
- Detection vs ground truth: every injected scenario type is detected.
- Story: the v1 prompt-injection rule produced 732 false positives on a benign document. The rule was fixed to
  require a destination, and a regression test was added (docs/THREAT_MODEL.md).

## 8. Investigation assistant (2 min)

**Investigation Assistant**:
1. "Why did run R-104 fail?" shows trace evidence, failed checks and runbook guidance, with evidence links.
2. "Compare rag-helpdesk 2.0.0 and 2.1.0 for latency, cost and task success."
3. "What is the capital of Australia?" The assistant declines because it has no evidence.

Note the mode badge. Answers are deterministic and grounded. An LLM is optional and may only rephrase the evidence.

## 9. Orchestration (1 min, optional)

**Airflow**: three DAGs.
- `daily_agent_regression` produces the suite through Kafka, waits for the lakehouse, gates every agent and scores anomalies.
- `lakehouse_maintenance`: DQ gate → summaries + compaction → snapshot expiry.
- `anomaly_model_refresh`.

Show a successful run's graph.

## 10. Reports and limitations (1 min)

**Reports**: download CSV, or open the printable report and use Save as PDF.

Close with the limitations:
- single node;
- simulated model latency;
- no authentication (local demo, ports bound to 127.0.0.1);
- heuristic security rules.

## Likely questions

| Question | Answer |
|---|---|
| Is this distributed? | The architecture is (Kafka, Spark, Trino, Iceberg), but the measurements are single-node. We report them as such and do not extrapolate. |
| Are these real LLM latencies? | No. Mock agents simulate latency and tokens from version profiles. The pipeline, query and storage numbers are real. |
| How do you know the detectors work? | Synthetic ground-truth labels, a dev/holdout split, thresholds chosen without labels, precision/recall/F1 per fault type, and false-positive rates on clean traffic. |
| What happens to bad data? | Quarantined with a reason in bronze plus a dead-letter table. Semantic issues are kept and flagged by data-quality SQL. Tests assert exact counts. |
| Exactly-once? | Effectively-once per Kafka offset in bronze (measured: 0 duplicated offsets across restarts). Producer duplicates are detected by DQ SQL. |
| Can a user run arbitrary SQL? | No. Only the curated read-only catalog, with typed prepared-statement parameters, a timeout, memory limits and row limits. |

## If something goes wrong

- A page shows an error panel: check `docker compose ps` and Pipeline Health. Restart one service with
  `docker compose restart <service>`.
- The live run does not start (HTTP 409): another test run is active. Stop it from the Testing Lab.
- Spark is behind: Pipeline Health shows consumer lag. It catches up at about 12k rows/s, so wait.
- Worst case, all pre-loaded data is still queryable. Skip step 2.
