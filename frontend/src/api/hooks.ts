import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "./client";
import type {
  Agent,
  AnomalyDetail,
  AnomalyRow,
  AnomalySummary,
  Comparison,
  CaseAnalytics,
  CaseEvidenceItem,
  CaseFilters,
  FindingRow,
  GateLive,
  GateStored,
  InvestigationContext,
  InvestigationHistoryItem,
  InvestigationResponse,
  InvestigationSession,
  InvestigationTurn,
  LinkedFinding,
  Overview,
  Paged,
  PagedSessions,
  PipelineHealth,
  QueryResult,
  RunRow,
  Scenario,
  SecurityCase,
  SecurityPolicy,
  SecuritySummary,
  SessionAnalytics,
  SessionFilters,
  SqlShowcase,
  StartTestRunResponse,
  TestRunDetail,
  TestRunList,
  TimelineEntry,
  Trace,
  TurnFeedback,
} from "./types";

type QR = QueryResult;

export const useOverview = (days: number) =>
  useQuery({ queryKey: ["overview", days], queryFn: () => api<Overview>(`/api/v1/overview${qs({ days })}`), placeholderData: keepPreviousData });

export const usePipelineHealth = (refetchMs?: number) =>
  useQuery({
    queryKey: ["pipeline-health"],
    queryFn: () => api<PipelineHealth>("/api/v1/pipeline/health"),
    refetchInterval: refetchMs,
    staleTime: refetchMs ? Math.min(refetchMs, 30_000) : 30_000,
  });

export const useAgents = () =>
  useQuery({ queryKey: ["agents"], queryFn: () => api<{ agents: Agent[] }>("/api/v1/agents"), staleTime: 5 * 60_000 });

export const useScenarios = () =>
  useQuery({ queryKey: ["scenarios"], queryFn: () => api<{ scenarios: Scenario[]; faults: string[] }>("/api/v1/scenarios"), staleTime: 5 * 60_000 });

export const useTestRuns = (limit = 50, refetchMs?: number | false | ((q: { state: { data?: TestRunList } }) => number | false)) =>
  useQuery({
    queryKey: ["test-runs", limit],
    queryFn: () => api<TestRunList>(`/api/v1/test-runs${qs({ limit })}`),
    refetchInterval: refetchMs,
  });

export const useTestRun = (id: string | null, poll: boolean) =>
  useQuery({
    queryKey: ["test-run", id],
    queryFn: () => api<TestRunDetail>(`/api/v1/test-runs/${encodeURIComponent(id!)}`),
    enabled: !!id,
    refetchInterval: poll ? 3000 : false,
    staleTime: poll ? 0 : 30_000,
  });

export const useStartTestRun = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<StartTestRunResponse>("/api/v1/test-runs", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["test-runs"] }),
  });
};

export const useStopTestRun = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api<{ test_run_id: string; stop_signalled: boolean; message: string }>(`/api/v1/test-runs/${encodeURIComponent(id)}/stop`, { method: "POST" }),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["test-runs"] });
      qc.invalidateQueries({ queryKey: ["test-run", id] });
    },
  });
};

export const useGateResults = (limit = 20) =>
  useQuery({ queryKey: ["gate-results", limit], queryFn: () => api<{ gates: GateStored[] }>(`/api/v1/regression-gate/results${qs({ limit })}`) });

export const useRunGate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<GateLive>("/api/v1/regression-gate", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gate-results"] }),
  });
};

export type RunFilters = Partial<{
  agent_id: string;
  agent_version: string;
  test_run_id: string;
  status: string;
  success: string;
  has_findings: string;
  min_latency_ms: string;
  run_id: string;
  sort: string;
}>;

export const useRuns = (days: number, filters: RunFilters, limit: number, offset: number) =>
  useQuery({
    queryKey: ["runs", days, filters, limit, offset],
    queryFn: () => api<Paged<RunRow>>(`/api/v1/runs${qs({ days, ...filters, limit, offset })}`),
    placeholderData: keepPreviousData,
  });

/** Trace by trace id (32 hex) or by run id (R-...), both return the same payload. */
export const useTrace = (id: string | undefined) =>
  useQuery({
    queryKey: ["trace", id],
    queryFn: () =>
      /^[0-9a-f]{32}$/.test(id!)
        ? api<Trace>(`/api/v1/traces/${id}`)
        : api<Trace>(`/api/v1/runs/${encodeURIComponent(id!)}`),
    enabled: !!id,
    staleTime: 5 * 60_000,
  });

export const usePerformance = (days: number) =>
  useQuery({ queryKey: ["perf", days], queryFn: () => api<Record<string, QR>>(`/api/v1/analytics/performance${qs({ days })}`), placeholderData: keepPreviousData });

export const useQuality = (days: number) =>
  useQuery({ queryKey: ["quality", days], queryFn: () => api<Record<string, QR>>(`/api/v1/analytics/quality${qs({ days })}`), placeholderData: keepPreviousData });

export const useRegressions = (days: number, scenario: string) =>
  useQuery({
    queryKey: ["regressions", days, scenario],
    queryFn: () => api<Record<string, QR>>(`/api/v1/analytics/regressions${qs({ days, scenario })}`),
    placeholderData: keepPreviousData,
  });

export const useComparison = (days: number, versions: string[]) =>
  useQuery({
    queryKey: ["comparison", days, versions],
    queryFn: () => api<Comparison>(`/api/v1/analytics/comparison${qs({ days, versions: versions.join(",") })}`),
    enabled: versions.length >= 2,
    placeholderData: keepPreviousData,
  });

// The API caps data-quality checks to recent partitions and reports the applied window next to the results.
export type DqWindow = { requested_days: number; applied_days: number; note: string };

export const useDataQuality = (days: number, enabled = true) =>
  useQuery({
    queryKey: ["data-quality", days],
    queryFn: async () => {
      const { window, ...results } = await api<Record<string, unknown>>(`/api/v1/analytics/data-quality${qs({ days })}`);
      return { window: window as DqWindow | undefined, results: results as Record<string, QR> };
    },
    enabled,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });

export const useSqlShowcase = () =>
  useQuery({ queryKey: ["sql-showcase"], queryFn: () => api<SqlShowcase>("/api/v1/analytics/sql-showcase"), staleTime: 10 * 60_000 });

export const useRunShowcase = () =>
  useMutation({
    mutationFn: ({ name, params }: { name: string; params: Record<string, string | number> }) =>
      api<QR>(`/api/v1/analytics/sql-showcase/${encodeURIComponent(name)}/run`, { method: "POST", body: params }),
  });

export type AnomalyFilters = Partial<{ severity: string; anomaly_type: string; detector: string; agent_id: string; test_run_id: string }>;

export const useAnomalies = (days: number, f: AnomalyFilters, limit: number, offset: number) =>
  useQuery({
    queryKey: ["anomalies", days, f, limit, offset],
    queryFn: () => api<Paged<AnomalyRow>>(`/api/v1/anomalies${qs({ days, ...f, limit, offset })}`),
    placeholderData: keepPreviousData,
  });

export const useAnomalySummary = (days: number) =>
  useQuery({ queryKey: ["anomaly-summary", days], queryFn: () => api<AnomalySummary>(`/api/v1/anomalies/summary${qs({ days })}`), placeholderData: keepPreviousData });

export const useAnomaly = (id: string | null) =>
  useQuery({ queryKey: ["anomaly", id], queryFn: () => api<AnomalyDetail>(`/api/v1/anomalies/${encodeURIComponent(id!)}`), enabled: !!id });

export const useAnomalyFeedback = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, verdict, note }: { id: string; verdict: string; note?: string }) =>
      api<{ id: number; alert_id: string; verdict: string; created_at: string }>(`/api/v1/anomalies/${encodeURIComponent(id)}/feedback`, {
        method: "POST",
        body: { verdict, note: note || null },
      }),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["anomalies"] });
      qc.invalidateQueries({ queryKey: ["anomaly", v.id] });
      qc.invalidateQueries({ queryKey: ["anomaly-summary"] });
    },
  });
};

export type FindingFilters = Partial<{ severity: string; rule_id: string; category: string; action: string; agent_id: string; test_run_id: string }>;

export const useFindings = (days: number, f: FindingFilters, limit: number, offset: number) =>
  useQuery({
    queryKey: ["findings", days, f, limit, offset],
    queryFn: () => api<Paged<FindingRow>>(`/api/v1/security/findings${qs({ days, ...f, limit, offset })}`),
    placeholderData: keepPreviousData,
  });

export const useSecuritySummary = (days: number) =>
  useQuery({ queryKey: ["security-summary", days], queryFn: () => api<SecuritySummary>(`/api/v1/security/summary${qs({ days })}`), placeholderData: keepPreviousData });

export const useSecurityPolicy = () =>
  useQuery({ queryKey: ["security-policy"], queryFn: () => api<SecurityPolicy>("/api/v1/security/policy"), staleTime: 5 * 60_000 });

export const useInvestigationExamples = () =>
  useQuery({ queryKey: ["inv-examples"], queryFn: () => api<{ examples: string[] }>("/api/v1/investigations/examples"), retry: false, staleTime: 5 * 60_000 });

export const useInvestigationHistory = (limit = 20) =>
  useQuery({
    queryKey: ["inv-history", limit],
    queryFn: () => api<{ items: InvestigationHistoryItem[] }>(`/api/v1/investigations/history${qs({ limit })}`),
    retry: false,
  });

export const useInvestigate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { question: string; context: InvestigationContext; session_id?: string }) =>
      api<InvestigationResponse>("/api/v1/investigations", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inv-history"] });
      qc.invalidateQueries({ queryKey: ["inv-sessions"] });
    },
  });
};

// ---------- investigation sessions (MongoDB) ----------
export const useInvestigationSessions = (filters: SessionFilters = {}, limit = 50, offset = 0) =>
  useQuery({
    queryKey: ["inv-sessions", filters, limit, offset],
    queryFn: () => api<PagedSessions>(`/api/v1/investigations/sessions${qs({ ...filters, limit, offset })}`),
    placeholderData: keepPreviousData,
  });

export const useInvestigationSession = (sessionId: string | null) =>
  useQuery({
    queryKey: ["inv-session", sessionId],
    queryFn: () => api<InvestigationSession>(`/api/v1/investigations/sessions/${encodeURIComponent(sessionId!)}`),
    enabled: !!sessionId,
  });

export const useSessionAnalytics = () =>
  useQuery({
    queryKey: ["inv-session-analytics"],
    queryFn: () => api<SessionAnalytics>("/api/v1/investigations/sessions/summary/analytics"),
    staleTime: 60_000,
  });

export const useCreateSession = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      title?: string;
      analyst?: string;
      scope_context?: InvestigationContext;
      initial_question?: string;
      tags?: string[];
      use_llm?: boolean;
    }) =>
      api<InvestigationSession>("/api/v1/investigations/sessions", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inv-sessions"] });
      qc.invalidateQueries({ queryKey: ["inv-session-analytics"] });
    },
  });
};

export const useAddSessionTurn = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      question,
      contextOverride,
      useLlm,
    }: {
      sessionId: string;
      question: string;
      contextOverride?: InvestigationContext;
      useLlm?: boolean;
    }) =>
      api<{ session_id: string; turn: InvestigationTurn; turn_count: number }>(
        `/api/v1/investigations/sessions/${encodeURIComponent(sessionId)}/turns`,
        {
          method: "POST",
          body: {
            question,
            context_override: contextOverride,
            use_llm: useLlm ?? false,
          },
        }
      ),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["inv-session", v.sessionId] });
      qc.invalidateQueries({ queryKey: ["inv-sessions"] });
      qc.invalidateQueries({ queryKey: ["inv-session-analytics"] });
      qc.invalidateQueries({ queryKey: ["inv-history"] });
    },
  });
};

export const useSubmitTurnFeedback = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      turnId,
      rating,
      verdict,
      notes,
      submittedBy,
    }: {
      sessionId: string;
      turnId: number;
      rating: number;
      verdict: string;
      notes?: string;
      submittedBy?: string;
    }) =>
      api<{ session_id: string; turn_id: number; feedback: TurnFeedback }>(
        `/api/v1/investigations/sessions/${encodeURIComponent(sessionId)}/turns/${turnId}/feedback`,
        {
          method: "PATCH",
          body: {
            rating,
            verdict,
            notes: notes || null,
            submitted_by: submittedBy,
          },
        }
      ),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["inv-session", v.sessionId] });
      qc.invalidateQueries({ queryKey: ["inv-session-analytics"] });
    },
  });
};

export const useUpdateSession = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      title,
      status,
      tags,
    }: {
      sessionId: string;
      title?: string;
      status?: "ACTIVE" | "ARCHIVED" | "CLOSED";
      tags?: string[];
    }) =>
      api<InvestigationSession>(
        `/api/v1/investigations/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "PATCH",
          body: { title, status, tags },
        }
      ),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["inv-session", v.sessionId] });
      qc.invalidateQueries({ queryKey: ["inv-sessions"] });
      qc.invalidateQueries({ queryKey: ["inv-session-analytics"] });
    },
  });
};

// ---------- security cases (MongoDB) ----------
export const useCases = (filters: CaseFilters, limit = 25, offset = 0) =>
  useQuery({
    queryKey: ["cases", filters, limit, offset],
    queryFn: () => api<Paged<SecurityCase>>(`/api/v1/cases${qs({ ...filters, limit, offset })}`),
    placeholderData: keepPreviousData,
  });

export const useCase = (caseId: string | null) =>
  useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api<SecurityCase>(`/api/v1/cases/${encodeURIComponent(caseId!)}`),
    enabled: !!caseId,
  });

export const useCaseAnalytics = (refetchMs?: number) =>
  useQuery({
    queryKey: ["case-analytics"],
    queryFn: () => api<CaseAnalytics>("/api/v1/cases/summary/analytics"),
    refetchInterval: refetchMs,
    staleTime: refetchMs ? Math.min(refetchMs, 30_000) : 30_000,
  });

export const useCreateCase = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<SecurityCase>("/api/v1/cases", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case-analytics"] });
    },
  });
};

export const useUpdateCase = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ caseId, body }: { caseId: string; body: Record<string, unknown> }) =>
      api<SecurityCase>(`/api/v1/cases/${encodeURIComponent(caseId)}`, { method: "PATCH", body }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case", vars.caseId] });
      qc.invalidateQueries({ queryKey: ["case-analytics"] });
    },
  });
};

export const useAddTimelineNote = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ caseId, body }: { caseId: string; body: { action: string; notes: string; author?: string; metadata?: Record<string, unknown> } }) =>
      api<{ case_id: string; timeline_entry: TimelineEntry }>(`/api/v1/cases/${encodeURIComponent(caseId)}/timeline`, { method: "POST", body }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case", vars.caseId] });
    },
  });
};

export const useAttachEvidence = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      caseId,
      body,
    }: {
      caseId: string;
      body: { kind: string; title: string; detail: string; ref?: string; metadata?: Record<string, unknown>; author?: string };
    }) => api<{ case_id: string; evidence_id: string; evidence_item: CaseEvidenceItem }>(`/api/v1/cases/${encodeURIComponent(caseId)}/evidence`, { method: "POST", body }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case", vars.caseId] });
    },
  });
};

export const useLinkFinding = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      caseId,
      body,
    }: {
      caseId: string;
      body: { finding_id: string; rule_id: string; rule_name?: string; severity: string; trace_id: string; span_id?: string; author?: string };
    }) => api<{ case_id: string; linked_findings: LinkedFinding[]; message: string }>(`/api/v1/cases/${encodeURIComponent(caseId)}/findings`, { method: "POST", body }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case", vars.caseId] });
      qc.invalidateQueries({ queryKey: ["case-analytics"] });
    },
  });
};

export const useEscalateFinding = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { finding_id: string; initial_notes?: string; priority?: string; created_by?: string }) =>
      api<SecurityCase>("/api/v1/cases/escalate-finding", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case-analytics"] });
    },
  });
};

export const useDeleteCase = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (caseId: string) => api<{ deleted: boolean; case_id: string }>(`/api/v1/cases/${encodeURIComponent(caseId)}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cases"] });
      qc.invalidateQueries({ queryKey: ["case-analytics"] });
    },
  });
};
