/* Response shapes, taken from the live API (curl) and backend source - not guessed. */

export type Row = Record<string, unknown>;

export interface TrinoStats {
  state?: string;
  elapsedTimeMillis?: number;
  cpuTimeMillis?: number;
  wallTimeMillis?: number;
  processedRows?: number;
  processedBytes?: number;
  physicalInputBytes?: number;
  peakMemoryBytes?: number;
  totalSplits?: number;
}

/** Result of one named catalog query (performance/quality/regressions/etc. and SQL showcase runs). */
export interface QueryResult<R = Row> {
  name: string;
  title?: string;
  params?: Record<string, unknown>;
  columns: string[];
  rows: R[];
  row_count?: number;
  truncated?: boolean;
  elapsed_ms?: number;
  trino_stats?: TrinoStats | null;
  query_id?: string;
  cached?: boolean;
}

// ---------- overview ----------
export interface HourlyTrendPoint {
  hour: string;
  runs: number;
  success_rate: number | null;
  p95_latency_ms: number | null;
}
export interface Overview {
  days: number;
  runs: {
    total_runs: number;
    test_runs: number;
    success_rate: number | null;
    p95_latency_ms: number | null;
    total_tokens: number | null;
    est_cost_usd: number | null;
    failed_runs: number;
  };
  events: number;
  security: { findings: number; critical: number };
  anomalies: { alerts: number; high_or_critical: number };
  quarantined_records: number;
  hourly_trend: HourlyTrendPoint[];
  cost_note?: string;
}

// ---------- pipeline ----------
export type ComponentStatus = "ok" | "degraded" | "down" | "unknown" | string;
export interface SparkBatch {
  batch_id: number;
  rows: number;
  trigger_ms: number;
  at: string;
}
export interface SparkQuery {
  status: string;
  last_batch_id?: number | null;
  last_progress_at?: string | null;
  last_input_rows?: number | null;
  input_rows_per_sec?: number | null;
  processed_rows_per_sec?: number | null;
  last_trigger_ms?: number | null;
  consumer_lag_messages?: number | null;
  watermark?: string | null;
  rows_dropped_by_watermark?: number | null;
  recent_batches?: SparkBatch[];
  exception?: string | null;
}
export interface PipelineComponent {
  status: ComponentStatus;
  error?: string;
  check_ms?: number;
  [k: string]: unknown;
}
export interface PipelineHealth {
  status: ComponentStatus;
  checked_at: string;
  components: {
    kafka?: PipelineComponent & {
      topics?: Record<string, { partitions: number; messages_total: number }>;
      missing_topics?: string[];
    };
    trino?: PipelineComponent & {
      ping_ms?: number;
      lakehouse_tables?: Record<string, { rows: number; bytes: number; files: number }>;
      recent_queries?: { window_minutes: number; finished: number; avg_ms: number | null; p95_ms: number | null };
    };
    postgres?: PipelineComponent;
    airflow?: PipelineComponent & { dags?: unknown };
    spark?: PipelineComponent & {
      heartbeat_age_s?: number;
      started_at?: string;
      queries?: Record<string, SparkQuery>;
    };
    [k: string]: PipelineComponent | undefined;
  };
}

// ---------- agents / scenarios ----------
export interface Agent {
  agent_id: string;
  agent_name: string;
  workload_type: string;
  description?: string;
  agent_version: string;
  release_seq?: number;
  released_at?: string;
  model_name: string;
  prompt_version: string;
  profile?: Record<string, unknown>;
  policy?: { allowed_tools: string[]; max_tool_calls: number; max_data_classification: string; runtime_role: string };
  source?: string;
}
export interface MixEntry {
  agent_id: string;
  version: string;
  weight: number;
}
export interface Scenario {
  id: string;
  file: string;
  name: string;
  description?: string;
  seed?: number;
  tasks?: number;
  workers?: number;
  time_mode?: "simulated" | "realtime";
  sim_days?: number;
  rate_per_sec?: number;
  workload_mix?: MixEntry[];
  fault_profile?: Record<string, number>;
  incidents?: unknown[];
  dirty_rate?: number;
  max_faults_per_run?: number;
}

// ---------- test runs ----------
export interface TestRunListItem {
  test_run_id: string;
  test_run_name?: string;
  status: string;
  seed?: number;
  requested_tasks?: number;
  workers?: number;
  time_mode?: string;
  scenario_file?: string;
  started_at?: string;
  ended_at?: string | null;
  total_runs?: number;
  total_events?: number;
  triggered_by?: string;
  source: "lakehouse" | "api" | string;
  api_status?: string;
  progress_tasks?: number;
}
export interface TestRunList {
  test_runs: TestRunListItem[];
  active: string[];
}
export interface TestRunDetail {
  test_run_id: string;
  lakehouse: (Row & { test_run_name?: string; status?: string; requested_tasks?: number; total_runs?: number; total_events?: number; started_at?: string; ended_at?: string | null; time_mode?: string; triggered_by?: string; notes?: string | null }) | null;
  operational: {
    test_run_id: string;
    name: string;
    status: string;
    config?: Row;
    progress_tasks?: number;
    summary?: Row & { events_per_sec?: number; tasks_per_sec?: number; wall_seconds?: number; events_emitted?: number; tasks_completed?: number; tasks_requested?: number };
    error?: string | null;
    stop_requested?: boolean;
    created_at?: string;
    updated_at?: string;
  } | null;
  stats: {
    runs_landed: number;
    success_rate: number | null;
    p50_latency_ms: number | null;
    p95_latency_ms: number | null;
    tokens: number | null;
    est_cost_usd: number | null;
    failed_runs: number | null;
    first_event: string | null;
    last_event: string | null;
  };
  ingest: { events_landed: number; invalid_events: number; first_ingested: string | null; last_ingested: string | null };
  by_agent: { agent_id: string; agent_version: string; runs: number; success_rate: number | null; p95_latency_ms: number | null }[];
  security_findings: { severity: string; n: number }[];
  anomaly_alerts: number;
  regression_gates: { gate_id: string; agent_id: string; baseline_version: string; candidate_version: string; verdict: string; evaluated_at: string }[];
}
export interface StartTestRunResponse {
  test_run_id: string;
  status: string;
  status_url: string;
  config: Row;
}

// ---------- regression gate ----------
export type Verdict = "PASSED" | "NEEDS_REVIEW" | "FAILED" | "INSUFFICIENT_DATA" | string;
/** Stored result shape (GET /regression-gate/results). */
export interface GateStored {
  gate_id: string;
  evaluated_at: string;
  agent_id: string;
  baseline_version: string;
  candidate_version: string;
  scenario_id: string | null;
  test_run_id: string | null;
  verdict: Verdict;
  baseline_runs: number;
  candidate_runs: number;
  success_p_value: number | null;
  checks: {
    check_name: string;
    unit: string;
    baseline_value: number | null;
    candidate_value: number | null;
    delta: number | null;
    review_threshold: number;
    fail_threshold: number;
    check_status: string;
    note: string;
  }[];
}
/** Live result shape (POST /regression-gate) - a dataclass asdict(). */
export interface GateCohort {
  agent_id: string;
  version: string;
  runs: number;
  successes: number;
  success_rate: number | null;
  p95_latency_ms: number | null;
  avg_tokens: number | null;
  cost_per_success: number | null;
  recall_at_k: number | null;
  findings_per_1k: number | null;
}
export interface GateLive {
  gate_id: string;
  evaluated_at: string;
  agent_id: string;
  baseline: GateCohort;
  candidate: GateCohort;
  scenario_id: string | null;
  test_run_id: string | null;
  verdict: Verdict;
  checks: { name: string; unit: string; baseline: number | null; candidate: number | null; delta: number | null; review: number; fail: number; status: string; note: string }[];
  success_rate_p_value: number | null;
}

// ---------- runs / traces ----------
export interface RunRow {
  run_id: string;
  trace_id: string;
  test_run_id: string;
  scenario_id: string;
  agent_id: string;
  agent_name: string;
  agent_version: string;
  model_name: string;
  workload_type: string;
  difficulty: string;
  status: string;
  task_success: boolean;
  error_category: string | null;
  event_time: string;
  latency_ms: number;
  ttft_ms: number | null;
  total_tokens: number;
  estimated_cost_usd: number | null;
  tool_calls: number;
  tool_errors: number;
  retries: number;
  span_count: number;
  policy_denials: number;
  injected_faults: string[] | null;
}
export interface Paged<R> {
  rows: R[];
  limit: number;
  offset: number;
  has_more: boolean;
  note?: string;
}
export interface Span {
  span_id: string;
  parent_span_id: string | null;
  span_kind: string;
  span_name: string;
  start_time: string;
  end_time: string;
  duration_ms: number;
  status: string;
  error_category: string | null;
  step_index: number | null;
  attempt: number | null;
  depth: number | null;
  model_name: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  ttft_ms: number | null;
  tool_name: string | null;
  tool_args_valid: boolean | null;
  tool_allowed: boolean | null;
  policy_decision: string | null;
  data_classification: string | null;
  retrieved_doc_ids: string[] | null;
  retrieval_scores: number[] | null;
  top_k: number | null;
  delegated_agent_id: string | null;
  attributes: Record<string, unknown> | null;
  dq_flags: string[] | null;
}
export interface Evaluation {
  evaluator_name: string;
  evaluator_version: string;
  evaluator_type: string;
  metric_name: string;
  score: number | null;
  passed: boolean | null;
  threshold: number | null;
  rubric: string | null;
  evidence: string | null;
}
export interface TraceFinding {
  finding_id: string;
  rule_id: string;
  rule_name: string;
  category: string;
  severity: string;
  span_id: string | null;
  tool_name: string | null;
  action: string;
  detector: string;
  evidence: string | null;
  policy_version: string;
  event_time: string;
}
export interface TraceAlert {
  alert_id: string;
  detector: string;
  anomaly_type: string;
  severity: string;
  score: number | null;
  explanation: string;
  supporting_metrics: Record<string, number | null> | null;
}
export interface Trace {
  trace_id: string;
  run: (Row & RunRow & { start_time?: string; end_time?: string; input_tokens?: number; output_tokens?: number; llm_calls?: number; tool_timeouts?: number; max_depth?: number; cost_source?: string; prompt_version?: string; task_id?: string; worker_id?: string; dq_flags?: string[] }) | null;
  spans: Span[];
  evaluations: Evaluation[];
  security_findings: TraceFinding[];
  anomaly_alerts: TraceAlert[];
}

// ---------- anomalies ----------
export interface FeedbackItem {
  verdict: string;
  note: string | null;
  reviewer: string;
  created_at: string;
}
export interface AnomalyRow {
  alert_id: string;
  detector: string;
  detector_version?: string;
  anomaly_type: string;
  severity: string;
  score: number | null;
  agent_id: string;
  agent_name?: string;
  agent_version: string;
  test_run_id: string | null;
  run_id: string | null;
  trace_id: string | null;
  window_start?: string | null;
  window_end?: string | null;
  related_run_ids?: string[] | null;
  related_trace_ids?: string[] | null;
  supporting_metrics?: Record<string, number | null> | null;
  explanation: string;
  event_time: string;
  feedback?: FeedbackItem[];
}
export interface Confusion {
  tp: number;
  fp: number;
  fn: number;
  tn: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  false_positive_rate: number | null;
}
export interface DetectorEvaluation {
  recorded_at?: string;
  model_version?: string;
  model_training_scenarios?: string[];
  eval_scenario?: string;
  eval_runs?: number;
  positives?: number;
  overall?: Record<string, Confusion>;
  isolation_forest_roc_auc?: number | null;
  per_fault_recall?: Record<string, { runs: number; rules?: number | null; isolation_forest?: number | null; combined?: number | null }>;
  alerts_by_detector?: Record<string, number>;
  isolation_forest_operating_points?: Record<string, Confusion & { threshold: number }>;
  incident_windows?: {
    incidents?: { incident: string; agent: string; start: string; end: string; runs: number; detected_by_window_rule: boolean; window_alerts: number }[];
    window_alerts_total?: number;
    window_alerts_outside_incidents?: number;
  };
  clean_traffic?: { scenario: string; runs: number; runs_with_perf_labels?: number; rules_flag_rate?: number; isolation_forest_flag_rate?: number; combined_flag_rate?: number };
  file?: string;
}
export interface AnomalySummary {
  by_detector_type_severity: { detector: string; anomaly_type: string; severity: string; alerts: number; agents: number }[];
  by_agent_version: { agent_id: string; agent_version: string; alerts: number; high_or_critical: number }[];
  feedback_verdicts: Record<string, number>;
  detector_evaluation: DetectorEvaluation | null;
  model: (Row & {
    model_version?: string;
    trained_at?: string;
    algorithm?: string;
    params?: Record<string, unknown>;
    features?: string[];
    feature_transform?: string;
    threshold?: number;
    threshold_rule?: string;
    training?: { scenarios?: string[]; runs?: number; test_run_ids?: string[]; agent_versions?: number };
  }) | null;
  note?: string;
}
export interface AnomalyDetail {
  alert: AnomalyRow & Row;
  related_runs: Row[];
  feedback: FeedbackItem[];
  note?: string;
}

// ---------- security ----------
export interface FindingRow {
  finding_id: string;
  event_time: string;
  rule_id: string;
  rule_name: string;
  category: string;
  severity: string;
  action: string;
  detector: string;
  agent_id: string;
  agent_version: string;
  test_run_id: string | null;
  run_id: string | null;
  trace_id: string | null;
  span_id: string | null;
  tool_name: string | null;
  evidence: string | null;
  policy_version: string;
  rule_description?: string | null;
  span_kind?: string | null;
  span_name?: string | null;
  policy_decision?: string | null;
  data_classification?: string | null;
}
export interface SecuritySummary {
  by_rule: QueryResult;
  detection_vs_ground_truth: QueryResult;
  highest_risk: QueryResult;
  by_agent: { agent_id: string; agent_version: string; findings: number; critical: number; blocked: number; affected_runs: number }[];
  note?: string;
}
export interface PolicyRule {
  rule_id: string;
  rule_name: string;
  category: string;
  severity: string;
  description: string;
}
export interface SecurityPolicy {
  policy: {
    policy_version: string;
    data_classifications?: string[];
    agents?: Record<string, { allowed_tools: string[]; max_tool_calls: number; max_data_classification: string; runtime_role: string }>;
    prohibited_tools?: string[];
    egress_tools?: string[];
    restricted_resources?: string[];
    sensitive_patterns?: { name: string; regex: string }[];
    prompt_injection_indicators?: string[];
    privilege?: { expected_role?: string; elevated_roles?: string[] };
    rules?: PolicyRule[];
    [k: string]: unknown;
  };
  source?: string;
  note?: string;
}

// ---------- analytics ----------
export interface SqlShowcaseQuery {
  name: string;
  file: string;
  title: string;
  concept?: string;
  question?: string;
  interpretation?: string;
  params: Record<string, string | number>;
  sql: string;
}
export interface SqlShowcase {
  count: number;
  queries: SqlShowcaseQuery[];
}
export interface ComparisonRow {
  agent_id: string;
  agent_version: string;
  agent_name: string;
  model_name: string;
  prompt_version: string;
  runs: number;
  success_rate: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_tokens: number | null;
  est_cost_usd: number | null;
  est_cost_per_success: number | null;
  avg_retries: number | null;
  exact_match: number | null;
  schema_validity: number | null;
  recall_at_k: number | null;
  hallucination_flag_rate: number | null;
  security_findings: number | null;
  critical_findings: number | null;
  findings_per_1k_runs: number | null;
  anomaly_alerts: number | null;
}
export interface Comparison {
  days: number;
  versions: string[];
  rows: ComparisonRow[];
  cost_note?: string;
}

// ---------- investigations (contract; service built in parallel) ----------
export type EvidenceKind = "run" | "trace" | "metric" | "sql" | "document" | "policy" | "alert" | "finding" | string;
export interface Evidence {
  kind: EvidenceKind;
  ref: string;
  title: string;
  detail: string;
}
export interface InvestigationContext {
  test_run_id?: string;
  run_id?: string;
  trace_id?: string;
  agent_id?: string;
  agent_version?: string;
  baseline_version?: string;
}
export interface InvestigationResponse {
  question: string;
  intent: string;
  mode: "deterministic" | "llm" | string;
  answer: string;
  evidence: Evidence[];
  grounded: boolean;
  limitations: string;
  suggested_questions: string[];
  data?: unknown;
}
export interface InvestigationHistoryItem {
  question?: string;
  intent?: string;
  mode?: string;
  grounded?: boolean;
  created_at?: string;
  answer?: string;
  [k: string]: unknown;
}
