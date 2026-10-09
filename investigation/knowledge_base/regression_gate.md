# Runbook: reading a regression gate result

The gate compares a candidate version with its baseline on the same scenario. It checks the success-rate drop
(percentage points, with a two-proportion z-test p-value), the p95 latency increase, the average token increase,
the estimated cost-per-success increase, the Recall@K drop (RAG agents) and security findings per 1,000 runs.

- PASSED: no threshold breached.
- NEEDS_REVIEW: a review bound was breached; a human decides.
- FAILED: a fail bound was breached. Do not promote without an explicit, documented exception.
- INSUFFICIENT_DATA: fewer runs than min_runs_per_cohort; collect more data.

Trade-offs are common. A version can be faster and cheaper while answering worse (RAG Helpdesk 2.1.0), or more
accurate while slower and more expensive (QA Assistant 1.1.0). The gate surfaces the trade-off; promotion
remains a human decision.
