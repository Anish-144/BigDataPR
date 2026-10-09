# Runbook: anomaly alerts

## Detectors
- Rule detectors (explainable): latency, token and tool-latency spikes relative to the agent version's robust
  baseline (median + 6 robust SD), suspected loops, long chains and tool timeouts, plus window rules (binomial
  tests for error-rate spikes and latency regressions, Bonferroni-corrected).
- Isolation Forest: an unsupervised multivariate detector over per-version normalised run features.

## Interpreting alerts
An alert is an unusual execution pattern, not automatically a bug or an attack. On a held-out labelled scenario
the rules had precision 1.0 and recall 0.63, and the combined detectors reached F1 0.77 at a 0.76% false-positive
rate. Quality-only failures (for example irrelevant retrieval without errors) are not visible in performance
telemetry; they are covered by evaluation metrics and the regression gate instead.

## Feedback
Mark alerts as useful or noisy in the Anomaly Center. Feedback is stored for detector review; it never changes
thresholds automatically.
