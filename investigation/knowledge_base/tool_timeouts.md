# Runbook: tool timeouts

## What a tool timeout means
A tool call that does not answer within the 8,000 ms tool timeout is recorded as a `tool_call` span with
`status = timeout` and `error_category = tool_timeout`. The agent retries up to two more times. When every
attempt times out, the run ends with `status = timeout`.

## Likely causes
- A slow or unavailable dependency behind the tool (order system, ticket system, document store).
- Retry storms: retries multiply load on an already slow dependency and increase end-to-end latency.
- A timeout budget that is too low for the tool's normal p95 latency.

## How to investigate
- Compare the tool's p95 latency and timeout count in the tool performance view (sql/02 tool_performance).
- Check whether timeouts cluster in a time window (incident) or are spread out (chronic).
- Open affected traces: timed-out spans show attempt numbers and the 8,000 ms duration.

## Recommended actions (human-approved)
- Add a circuit breaker or fallback answer when a tool is unavailable instead of retrying immediately.
- Use exponential backoff between retries and cap total retry time per run.
- Raise the timeout only if the tool's normal p99 is close to it; otherwise fix the dependency.
