# Benchmark methodology

The goal is repeatable, honest measurement on one machine. Every reported number comes from a script that writes
JSON/CSV to `benchmarks/results/`. `docs/BENCHMARK_REPORT.md` is generated from those files
(`python -m docs.generate_docs benchmarks`). No value is typed in by hand.

## 1. Environment capture

Each pipeline benchmark records:
- host CPU count, RAM, OS and Python version (psutil / platform);
- Docker CPUs, memory, server version and OS (`docker info`);
- stack versions;
- container CPU and memory at completion (`docker stats`).

The reference machine has 24 logical CPUs and 16 GB RAM, with Docker Desktop on WSL2 limited to 7.6 GiB.
Container memory limits are in `docker-compose.yml`.

## 2. Workloads

| Workload | Scenario file | Seed | Purpose |
|---|---|---|---|
| Functional smoke | `smoke.yaml` | 7 | ~5k events, every fault + 1% dirty data |
| Baseline traffic | `baseline.yaml` | 42 | 20k tasks over 3 simulated days, rare faults, one incident window; trends, detector training |
| A/B regression | `regression_v1_v2.yaml` | 1234 | 8k tasks, no faults; version comparison and regression gate |
| Anomaly dev set | `fault_injection.yaml` | 99 | Labelled performance faults; detector design iterations |
| Anomaly holdout | `fault_injection_holdout.yaml` | 4242 | New seed and unseen incident types; **final** detector numbers |
| Security suite | `security_suite.yaml` | 2026 | Labelled security scenarios + benign near-misses |
| Volume | `benchmark.yaml` | 31337 | 1M / 5M event pipeline benchmarks |

Events per task are calibrated before each volume run: 1,500 tasks are simulated in-process with no I/O, and the
target event count is divided by the measured rate (about 14.5 events per task). Fixed seeds make every workload
reproducible. Identical IDs and identical regression verdicts were observed on re-runs.

## 3. Metric definitions

| Metric | Definition | Where measured |
|---|---|---|
| Producer throughput | events sent / wall time of the generator (all workers, until flush) | `generator.producer` summary |
| End-to-end time | from producer start until the bronze row count reaches the Kafka total for the run | `benchmarks/pipeline_benchmark.py` (5 s polling) |
| Spark throughput (span) | rows in micro-batches of the run / (last batch end - first batch start) | `pipeline_batch_metrics` |
| Spark throughput (busy) | rows / sum of micro-batch durations | `pipeline_batch_metrics` |
| Ingest lag | batch commit time - Kafka record timestamp (avg and max per batch) | `pipeline_batch_metrics` |
| Invalid/dropped events | quarantined records by reason vs the generator's injected ground truth | `dead_letter_events` vs producer summary |
| Storage footprint | sum of `file_size_in_bytes` from Iceberg `$files` metadata, before vs after | Trino metadata tables |
| Query latency | client wall time, median of N runs after one warm-up; Trino processed rows/bytes from query stats | `benchmarks/sql_benchmark.py` |
| Agent latency p50/p95/p99 | `approx_percentile` over `agent_run_metrics.latency_ms` of the run (**simulated** by mock agents) | Trino |
| Detector precision/recall/F1 | per-run labels from `injected_faults` (performance faults + incident windows) vs per-run detections | `ml/evaluate_detector.py` |
| Security detection rate | labelled runs whose expected rule category fired / labelled runs; findings on unlabelled runs | sql/05 `security_detection_vs_ground_truth` |

## 4. Procedures

```bash
scripts/reset_demo.sh --yes                     # optional clean slate
scripts/generate_demo_data.sh                   # standard dataset
.venv/Scripts/python -m benchmarks.pipeline_benchmark --events 1000000 --workers 6
.venv/Scripts/python -m benchmarks.pipeline_benchmark --events 5000000 --workers 6
.venv/Scripts/python -m lakehouse.run_sql sql/07_summary_tables.sql --quiet
.venv/Scripts/python -m benchmarks.sql_benchmark --runs 5
.venv/Scripts/python -m ml.train_anomaly_model --scenarios baseline regression
.venv/Scripts/python -m ml.evaluate_detector --eval-scenario fault_injection_holdout
.venv/Scripts/python -m docs.generate_docs benchmarks
```

The SQL experiment (spec section 9.3) answers the same question in three tiers:
1. raw JSON (schema-on-read over bronze);
2. curated, partitioned Iceberg facts;
3. the pre-aggregated summary table.

It also measures partition pruning (one day vs all data) and table layout: point lookups on the
streaming-written table vs a `trace_id`-sorted copy, with default and with 1 MB Parquet row groups. EXPLAIN /
EXPLAIN ANALYZE text is stored with the results.

## 5. Fairness and validity rules

- **Repeated runs.** One warm-up run, then the median of N runs. Min and max are kept in the JSON.
- **Measured, not assumed.** No speed-up is promised. Where a measurement shows no gain, the result is reported as-is.
  - Partition pruning halved the rows and bytes read but did not change latency at this data size.
  - Compaction reduced file counts about 3x without a latency gain.
  - Sorting alone did not reduce rows read.
- **Held-out evaluation.** Detector thresholds are not tuned on labels. The Isolation Forest threshold is a
  training-score quantile computed without labels. Design iterations used the dev scenario; final numbers come
  from the holdout scenario, which was generated after the last design change.
- **Simulated latency.** Agent latency and token counts are simulated by deterministic mock agents (version
  profiles). Pipeline, storage and query measurements are real.
- **Single node only.** All results are single-machine (one Kafka broker, Spark `local[4]`, one Trino node).
  They show the architecture works at the stated volumes; they are not distributed-scaling claims.
- **Concurrent load disclosed.** Other activity during a run (for example a dashboard build) affects results.
  Volume benchmarks were run with the stack otherwise idle where possible.

## 6. Known measurement limitations

- End-to-end completion is detected by 5-second polling, so it can overstate the time by up to 5 s.
- Ingest lag for a burst is dominated by queueing behind `maxOffsetsPerTrigger` (300k records per batch).
  It describes backlog drain, not steady-state latency.
- `approx_percentile` is approximate. sql/02 `exact_vs_approx_p95` measures the error, which was below 1%.
- Container memory is a point-in-time snapshot at completion, not a peak (except where noted).
