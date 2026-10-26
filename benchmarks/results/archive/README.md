# Archived measurements

Kept for transparency; superseded by the files in `benchmarks/results/`. Nothing here is used by
`docs/BENCHMARK_REPORT.md`.

| File(s) | Why archived |
|---|---|
| `detector_eval_20261009T1808*`, `..T1811*`, `..T1812*` | Detector design iterations on the dev scenario (v1 rules, v2 rules, Bonferroni window tests) before the clean rebuild. |
| `pipeline_benchmark_1000000_20261009T180729Z.*` | 1M-event run measured before the trace-ID scoping fix and the final dataset rebuild. Pipeline numbers were valid. |
| `sql_benchmark_20261009T152521Z.*` | SQL experiment on the 676k-event dataset before the rebuild. |
| `pipeline_benchmark_1000000_20261010T065527Z.*` | Pipeline numbers are valid, but the post-load *query latencies* (~2.2 s) are inflated by a client-side artifact. Host tools connected to `localhost`, which on Windows resolves to IPv6 `::1` first, while the ports were bound to IPv4 `127.0.0.1` only. Each new connection waited ~2 s before falling back (measured inside Trino: ~80 ms). Host defaults now use `127.0.0.1`, and the run was repeated. |
