# Runbook: data access, exfiltration and privilege changes

## Rules
- SEC-003 restricted data access: reading a document above the agent's max_data_classification
  (for example restricted HR or payroll records).
- SEC-005 sensitive data in output: synthetic canary values (AGSH-CANARY-...) or synthetic API keys in an answer.
- SEC-007 exfiltration-like sequence: a sensitive read followed by an egress tool call (http_post,
  send_external_email, export_data) in the same trace.
- SEC-006 unexpected privilege transition: the runtime role changed from agent_runtime to an elevated role.

## Investigation steps
Open the trace, find the policy_check or tool_call span named in the finding, check which document or resource
was read, and whether the egress attempt was blocked (policy_decision = deny).

## Recommended actions (human-approved)
Tighten data-classification limits per agent, keep egress tools off allowlists, rotate any real secret if a
real (non-synthetic) value ever appears, and review the agent prompt that requested the action.
