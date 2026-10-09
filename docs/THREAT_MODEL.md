# Threat model and security test scenarios

AgentShield has two security roles. It **detects** risky behaviour of the AI agents it tests, and it is itself a
data platform that must not become a risk. All agent data is synthetic: a fictional company, mock tools, and
canary secrets such as `AGSH-CANARY-5F1E9A3B`. No real credentials or personal data are used.

## 1. Assets and trust boundaries

| Asset | Where | Notes |
|---|---|---|
| Agent telemetry (spans, runs, evaluations, findings) | Kafka, Iceberg on MinIO | Synthetic; prompts/answers not stored unless CAPTURE_CONTENT=true (then redacted previews) |
| Policy configuration | `config/policies.yaml` | Policy-as-code, versioned (`policy_version`) |
| Operational state | PostgreSQL | Test-run requests, alert feedback, investigation log |
| Secrets | `.env` (not committed), container env | MinIO/Postgres demo credentials; optional `ANTHROPIC_API_KEY` |
| Detector models | `models/` | Isolation Forest + baseline profile |

Trust boundaries:
1. **Untrusted content → agent.** User input, retrieved documents and tool results are treated as untrusted data.
2. **Analyst → API.** Questions, filters and parameters are untrusted input.
3. **API → lakehouse.** Only fixed queries or catalog queries with bound parameters cross this boundary.
4. **Investigation assistant → LLM (optional).** The model receives evidence text only. It has no tools and no database access.

## 2. Threats to agents under test (what AgentShield detects)

| Threat | Rule / detector | Control type | How it is tested |
|---|---|---|---|
| Agent calls a tool outside its allowlist | SEC-001 (policy engine) | **Prevented**: call denied before execution | `suspicious_tool_access` fault |
| Agent attempts a prohibited action (`execute_shell`, `delete_records`, `export_data`, `modify_permissions`) | SEC-002 | **Prevented** | `policy_violation` fault |
| Agent reads data above its classification | SEC-003 | Detected + recorded | `exfiltration_sequence`, `sensitive_data_leak` faults |
| Prompt injection in user input or retrieved documents | SEC-004 (input/retrieval content guards) | Detected; injected instructions are never executed, and resulting tool calls are denied by SEC-001/002 | `prompt_injection` fault; naturally retrieved poisoned docs KB-018/KB-019 |
| Sensitive data (canary) in the agent's answer | SEC-005 (output guard, redacted evidence) | Detected | `sensitive_data_leak` fault |
| Unexpected privilege transition | SEC-006 (role monitor) | Detected | `privilege_escalation` fault |
| Sensitive read followed by an egress attempt | SEC-007 (sequence detector) | Detected; egress tools are not allowlisted, so the call is also denied | `exfiltration_sequence` fault |
| Runaway loops / tool-call storms | SEC-008 (tool budget) + loop rule | **Prevented** beyond the budget; loop alert | `loop` fault |

Mock tools run in a sandbox. There is no shell, filesystem or network access. The calculator evaluates arithmetic
through an AST whitelist, never `eval`. Tool arguments are validated against JSON Schemas, and dangerous tools
exist only as names the policy engine can deny.

### Measured detection on the controlled suite

The test suite `generator/scenarios/security_suite.yaml` injects each scenario at a known rate. Ground truth comes
from generator labels, which detectors never see. The query is
`sql/05_security_correlation.sql#security_detection_vs_ground_truth`. Current numbers are in
BENCHMARK_REPORT.md: every injected scenario type is detected 100% of the time, with 0 same-category findings on
unlabelled runs.

### Detector iteration log (evaluation-driven development)

1. **v1 prompt-injection rules.** The indicator `(send|forward|upload) ... data ... to` matched the benign
   security-awareness document KB-020 ("emails that ask you to send data to unknown addresses"). This produced
   732 false-positive findings on 632 clean runs. Injection detection was 90.1%; all 7 misses were runs where
   retrieval noise pushed the poisoned document out of top-k, so the agent was never exposed.
2. **v2.** The indicator now requires an explicit destination (an email address or URL). The `prompt_injection`
   fault now guarantees exposure, and the ground-truth label counts only documents whose *content* reached the
   agent. A unit test asserts that no benign corpus document triggers a rule. Result: 0 false positives on
   unlabelled runs.
3. The raw v1 measurements are in `benchmarks/results/detector_iteration_v1_measurement.json`.

These rules are heuristics. Rephrased or obfuscated injections (other languages, encodings, split instructions)
would evade regular expressions. The allowlist and prohibited-action controls are the real safety net, because
they do not depend on recognising the attack text.

## 3. Threats to the platform (STRIDE-style)

| Threat | Mitigation in this repository | Residual risk |
|---|---|---|
| SQL injection through API filters or query parameters | Fixed SQL or named catalog queries only. Parameters are type-checked against declared defaults and bound as prepared-statement parameters. Strings are limited to `[A-Za-z0-9_.:@-]`. API tests assert that injection payloads return 422 and never reach Trino. | Low |
| Arbitrary SQL execution | No SQL console. Only read-only `SELECT/WITH/EXPLAIN` catalog statements are exposed. | Low |
| Denial of service through expensive analytics | Trino query timeout (60 s), 512 MB per-query memory limit with spill, resource group capping concurrency at 6, API row limits, 15 s result cache | Medium (no rate limiting) |
| Unauthenticated access to write endpoints (start test runs, feedback) | Ports are bound to 127.0.0.1 by default (`BIND_ADDRESS`); one concurrent test run; task limits | **High if exposed**: there is no authentication or RBAC. This is a local demo only. |
| Prompt injection against the investigation assistant | The question is used only for regex intent detection and as delimited, untrusted text for the optional LLM. The LLM has no tools or database access, may only rephrase supplied evidence, and its evidence list cannot be changed. On failure the deterministic answer is kept. | Low |
| Hallucinated metrics in assistant answers | Deterministic answers are built only from query results. The optional LLM is instructed not to add facts. The assistant declines when there is no evidence. | Medium when an LLM is enabled (rephrasing can still err) |
| Secret leakage | `.env` is excluded from the image build context and the docs. Canary values are redacted in evidence. No API key reaches the frontend. | Low |
| Tampering with telemetry | Kafka has no authentication or TLS on the local network; bronze keeps raw bytes and Kafka coordinates for audit | High if exposed |
| Poisoned events / malformed producers | Contract validation at the producer, plus structural validation in Spark with quarantine and data-quality SQL | Low |
| Supply chain | Python dependencies pinned and container images version-pinned. The MinIO image is an archived Bitnami build. | Medium (no SBOM or signature verification) |

## 4. Out of scope / known gaps

- Authentication, authorization and TLS for any service (local single-user demo).
- Real LLM providers' own safety behaviour. The optional adapter only rephrases evidence.
- Encryption at rest on MinIO and in Postgres.
- Automatic remediation. Every recommendation requires human approval, and alert feedback never changes thresholds automatically.
