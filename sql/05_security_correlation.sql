-- =============================================================================
-- 05 - Security & governance analytics, anomaly correlation
-- Findings are produced by deterministic policy rules / content detectors on
-- SYNTHETIC test data; a finding is evidence to investigate, not proof of an attack.
-- =============================================================================

-- @query: findings_by_rule_and_severity
-- @title: Security findings by policy rule and severity
-- @concept: Join fact to dimension (dim_policy_rules), conditional aggregation by severity and action
-- @question: Which policy rules fire most, how severe are they, and how many attempts were blocked vs flagged?
-- @interpretation: 'blocked' = the runtime guard denied the action before execution; 'flagged' = detected and
--   recorded (content-based detections cannot be blocked retroactively).
-- @params: days=30
SELECT
    p.rule_id,
    p.rule_name,
    p.category,
    p.severity                                         AS rule_severity,
    count(f.finding_id)                                AS findings,
    count_if(f.action = 'blocked')                     AS blocked,
    count_if(f.action = 'flagged')                     AS flagged,
    count(DISTINCT f.run_id)                           AS affected_runs,
    count(DISTINCT f.agent_id)                         AS affected_agents
FROM lakehouse.analytics.dim_policy_rules p
LEFT JOIN lakehouse.analytics.agent_security_findings f
       ON f.rule_id = p.rule_id
      AND f.event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY p.rule_id, p.rule_name, p.category, p.severity
ORDER BY findings DESC;

-- @query: findings_with_trace_evidence
-- @title: Security findings with the span that triggered them
-- @concept: Multi-table join (finding -> span -> run) for evidence-linked results
-- @question: For recent critical findings, which tool/span triggered them and what did the policy decide?
-- @interpretation: Each finding is linked to its trace and span, so an analyst can open the exact step in the
--   trace waterfall. Evidence text is redacted for synthetic secrets.
-- @params: days=30
SELECT
    f.event_time,
    f.rule_id,
    f.severity,
    f.agent_id,
    f.agent_version,
    f.run_id,
    f.trace_id,
    s.span_kind,
    s.span_name,
    s.tool_name,
    s.policy_decision,
    s.status          AS span_status,
    m.status          AS run_status,
    f.evidence
FROM lakehouse.analytics.agent_security_findings f
JOIN lakehouse.analytics.agent_spans s
  ON s.trace_id = f.trace_id AND s.span_id = f.span_id AND s.event_date = f.event_date
JOIN lakehouse.analytics.agent_run_metrics m
  ON m.run_id = f.run_id AND m.event_date = f.event_date
WHERE f.severity = 'critical'
  AND f.event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY f.event_time DESC
LIMIT 25;

-- @query: anomaly_security_correlation
-- @title: Runs with anomaly alerts and/or security findings
-- @concept: LEFT JOINs across three fact tables on (run_id, trace_id)
-- @question: Which runs were both anomalous (performance) and security-relevant?
-- @interpretation: Overlap is a strong investigation signal (e.g. a loop that also exceeded the tool budget).
--   Correlation is not causation, and an anomaly is not automatically an attack.
-- @params: days=30
SELECT
    m.run_id,
    m.trace_id,
    m.agent_name,
    m.agent_version,
    m.latency_ms,
    m.output_tokens,
    a.anomaly_type,
    a.severity AS anomaly_severity,
    s.rule_id,
    s.severity AS security_severity
FROM lakehouse.analytics.agent_run_metrics m
LEFT JOIN lakehouse.analytics.agent_anomaly_alerts a
       ON m.run_id = a.run_id
      AND m.trace_id = a.trace_id
LEFT JOIN lakehouse.analytics.agent_security_findings s
       ON m.run_id = s.run_id
      AND m.trace_id = s.trace_id
WHERE (a.alert_id IS NOT NULL OR s.finding_id IS NOT NULL)
  AND m.event_date >= current_date - (:days * INTERVAL '1' DAY)
ORDER BY (a.alert_id IS NOT NULL AND s.finding_id IS NOT NULL) DESC, m.event_time DESC
LIMIT 50;

-- @query: window_correlation_perf_errors_security
-- @title: Hourly correlation of latency regressions, tool errors and security findings
-- @concept: Time-window join of three aggregated CTEs; corr() statistical aggregate
-- @question: In which hours did tail latency spike, and did tool errors or security findings rise at the same time?
-- @interpretation: Joining on (agent, hour) aligns signals that live in different tables. corr() quantifies how
--   strongly hourly tool errors track hourly p95 latency across all windows.
-- @params: days=30, agent_id='ops-tool-agent'
WITH perf AS (
    SELECT agent_id, agent_version, date_trunc('hour', event_time) AS hour,
           count(*) AS runs, approx_percentile(latency_ms, 0.95) AS p95_ms
    FROM lakehouse.analytics.agent_run_metrics
    WHERE agent_id = :agent_id AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
tool_err AS (
    SELECT agent_id, agent_version, date_trunc('hour', event_time) AS hour,
           count_if(status <> 'ok' AND tool_allowed) AS tool_failures
    FROM lakehouse.analytics.agent_spans
    WHERE span_kind = 'tool_call' AND agent_id = :agent_id
      AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
sec AS (
    SELECT agent_id, agent_version, date_trunc('hour', event_time) AS hour, count(*) AS findings
    FROM lakehouse.analytics.agent_security_findings
    WHERE agent_id = :agent_id AND event_date >= current_date - (:days * INTERVAL '1' DAY)
    GROUP BY 1, 2, 3
),
joined AS (
    SELECT p.agent_version, p.hour, p.runs, p.p95_ms,
           coalesce(t.tool_failures, 0) AS tool_failures,
           coalesce(s.findings, 0)      AS findings
    FROM perf p
    LEFT JOIN tool_err t ON t.agent_id = p.agent_id AND t.agent_version = p.agent_version AND t.hour = p.hour
    LEFT JOIN sec s      ON s.agent_id = p.agent_id AND s.agent_version = p.agent_version AND s.hour = p.hour
)
SELECT
    agent_version,
    hour,
    runs,
    round(p95_ms, 1)                                                          AS p95_ms,
    tool_failures,
    findings,
    round(corr(p95_ms, tool_failures) OVER (PARTITION BY agent_version), 3)  AS corr_p95_vs_tool_failures
FROM joined
ORDER BY tool_failures DESC, p95_ms DESC
LIMIT 20;

-- @query: exfiltration_sequences
-- @title: Traces with a sensitive read followed by an egress attempt
-- @concept: Sequence analysis with conditional MIN() per trace and a HAVING ordering constraint
-- @question: Which traces show a restricted-data access followed later by an egress tool attempt?
-- @interpretation: Reconstructs the exfiltration pattern in SQL from span facts independently of the runtime
--   detector (SEC-007), which is a useful cross-check of the detector.
-- @params: days=30
SELECT
    trace_id,
    min(run_id)                                                                                    AS run_id,
    min(agent_id)                                                                                  AS agent_id,
    min(start_time) FILTER (WHERE data_classification IN ('confidential', 'restricted')
                              AND span_kind IN ('tool_call', 'retrieval'))                         AS first_sensitive_read,
    min(start_time) FILTER (WHERE tool_name IN ('send_external_email', 'http_post', 'export_data')) AS first_egress_attempt,
    array_join(array_agg(DISTINCT tool_name) FILTER (WHERE tool_name IS NOT NULL), ',')           AS tools_used
FROM lakehouse.analytics.agent_spans
WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
GROUP BY trace_id
HAVING min(start_time) FILTER (WHERE data_classification IN ('confidential', 'restricted')
                                 AND span_kind IN ('tool_call', 'retrieval'))
     < min(start_time) FILTER (WHERE tool_name IN ('send_external_email', 'http_post', 'export_data'))
ORDER BY first_egress_attempt DESC
LIMIT 25;

-- @query: security_detection_vs_ground_truth
-- @title: Security rule detection rate and false positives vs synthetic ground truth
-- @concept: UNNEST of label arrays, LEFT JOIN, confusion-matrix style conditional aggregation
-- @question: For each injected security scenario, how often did the expected rule category fire, and how many
--   findings occurred on runs with no injected security scenario?
-- @interpretation: Ground truth = injected_faults labels written by the generator (never used by detectors).
--   'poisoned_document_retrieved' marks runs that retrieved a poisoned KB document without an injected fault -
--   prompt-injection findings there are true detections, not false positives.
-- @params: days=30
WITH labels AS (
    SELECT m.run_id, f AS label
    FROM lakehouse.analytics.agent_run_metrics m
    CROSS JOIN UNNEST(m.injected_faults) AS t(f)
    WHERE m.event_date >= current_date - (:days * INTERVAL '1' DAY)
),
expected AS (
    SELECT * FROM (VALUES
        ('suspicious_tool_access', 'tool_not_allowlisted'),
        ('policy_violation', 'policy_violation'),
        ('prompt_injection', 'prompt_injection'),
        ('poisoned_document_retrieved', 'prompt_injection'),
        ('sensitive_data_leak', 'sensitive_data_output'),
        ('exfiltration_sequence', 'exfiltration_sequence'),
        ('privilege_escalation', 'privilege_escalation')
    ) AS e(label, category)
),
found AS (
    SELECT DISTINCT run_id, category FROM lakehouse.analytics.agent_security_findings
    WHERE event_date >= current_date - (:days * INTERVAL '1' DAY)
),
per_label AS (
    SELECT e.label, e.category, count(*) AS labelled_runs, count(f.run_id) AS detected_runs
    FROM labels l
    JOIN expected e ON e.label = l.label
    LEFT JOIN found f ON f.run_id = l.run_id AND f.category = e.category
    GROUP BY e.label, e.category
),
unlabelled AS (
    SELECT f.category, count(DISTINCT f.run_id) AS runs_with_finding
    FROM found f
    WHERE NOT EXISTS (SELECT 1 FROM labels l JOIN expected e ON e.label = l.label WHERE l.run_id = f.run_id)
    GROUP BY f.category
)
SELECT
    p.label                                                   AS injected_scenario,
    p.category                                                AS expected_category,
    p.labelled_runs,
    p.detected_runs,
    round(100e0 * p.detected_runs / p.labelled_runs, 2)       AS detection_rate_pct,
    coalesce(u.runs_with_finding, 0)                          AS same_category_findings_on_unlabelled_runs
FROM per_label p
LEFT JOIN unlabelled u ON u.category = p.category
ORDER BY p.label;
