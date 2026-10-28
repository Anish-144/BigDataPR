import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  useAgents,
  useInvestigate,
  useInvestigationExamples,
  useInvestigationHistory,
  useTestRuns,
  useInvestigationSessions,
  useInvestigationSession,
  useSessionAnalytics,
  useCreateSession,
  useAddSessionTurn,
  useSubmitTurnFeedback,
  useUpdateSession,
} from "../api/hooks";
import type {
  Evidence,
  InvestigationContext,
  InvestigationResponse,
  InvestigationSession,
  InvestigationTurn,
  TurnVerdict,
} from "../api/types";
import { Card, Field, PageHeader } from "../components/ui/Card";
import { Select } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, SkeletonRows } from "../components/ui/states";
import { Badge, Tag } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { Markdown, idHref } from "../lib/markdown";
import { appPath } from "../lib/nav";
import { fmtDateTime } from "../lib/format";

interface LocalExchange {
  id: number;
  question: string;
  context: InvestigationContext;
  response?: InvestigationResponse;
  error?: unknown;
  pending: boolean;
}

const CTX_KEYS: (keyof InvestigationContext)[] = [
  "test_run_id",
  "run_id",
  "trace_id",
  "agent_id",
  "agent_version",
  "baseline_version",
];

const isUnavailable = (e: unknown) =>
  e instanceof ApiError && (e.status === 404 || e.status === 501 || e.status === 503 || e.status === 0);

export default function Assistant() {
  const [sp, setSp] = useSearchParams();
  const examples = useInvestigationExamples();
  const history = useInvestigationHistory(20);
  const investigate = useInvestigate();
  const agents = useAgents();
  const testRuns = useTestRuns(100);

  // MongoDB Multi-Turn Sessions Hooks
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(sp.get("session") || null);
  const [sessionSearch, setSessionSearch] = useState("");
  const [sessionStatusFilter, setSessionStatusFilter] = useState<string>("");
  const [showNewSessionModal, setShowNewSessionModal] = useState(false);
  const [newSessionTitle, setNewSessionTitle] = useState("");
  const [newSessionAnalyst, setNewSessionAnalyst] = useState("analyst_sec");

  const sessionsQuery = useInvestigationSessions({
    status: sessionStatusFilter || undefined,
    search: sessionSearch || undefined,
  });
  const activeSessionQuery = useInvestigationSession(selectedSessionId);
  const sessionAnalytics = useSessionAnalytics();
  const createSession = useCreateSession();
  const addTurn = useAddSessionTurn();
  const updateSession = useUpdateSession();

  const [question, setQuestion] = useState(sp.get("q") ?? "");
  const [ctx, setCtx] = useState<InvestigationContext>(() => {
    const c: InvestigationContext = {};
    for (const k of CTX_KEYS) {
      const v = sp.get(k);
      if (v) c[k] = v;
    }
    return c;
  });

  const [localLog, setLocalLog] = useState<LocalExchange[]>([]);
  const nextId = useRef(1);
  const bottom = useRef<HTMLDivElement>(null);

  // Auto-scroll on conversation update
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [localLog.length, activeSessionQuery.data?.turns?.length]);

  // Sync selected session ID to URL search params
  const selectSession = (id: string | null) => {
    setSelectedSessionId(id);
    const newParams = new URLSearchParams(sp);
    if (id) {
      newParams.set("session", id);
    } else {
      newParams.delete("session");
    }
    setSp(newParams);
  };

  const unavailable =
    (examples.isError && isUnavailable(examples.error)) ||
    localLog.some((x) => x.error && isUnavailable(x.error));

  const activeCtx = Object.entries(ctx).filter(([, v]) => v);
  const currentContextObj = Object.fromEntries(activeCtx) as InvestigationContext;

  const handleAsk = (q: string) => {
    const text = q.trim();
    if (!text || investigate.isPending || addTurn.isPending) return;

    if (selectedSessionId) {
      // Append turn to MongoDB session
      setQuestion("");
      addTurn.mutate(
        {
          sessionId: selectedSessionId,
          question: text,
          contextOverride: activeCtx.length > 0 ? currentContextObj : undefined,
          useLlm: false,
        },
        {
          onError: (err) => {
            console.error("Turn append failed", err);
          },
        }
      );
    } else {
      // Ad-hoc single question
      const id = nextId.current++;
      setLocalLog((l) => [...l, { id, question: text, context: currentContextObj, pending: true }]);
      setQuestion("");
      investigate.mutate(
        { question: text, context: currentContextObj },
        {
          onSuccess: (response) =>
            setLocalLog((l) => l.map((x) => (x.id === id ? { ...x, response, pending: false } : x))),
          onError: (error) =>
            setLocalLog((l) => l.map((x) => (x.id === id ? { ...x, error, pending: false } : x))),
        }
      );
    }
  };

  const handleCreateSession = (e: FormEvent) => {
    e.preventDefault();
    createSession.mutate(
      {
        title: newSessionTitle.trim() || undefined,
        analyst: newSessionAnalyst.trim() || "analyst_sec",
        scope_context: currentContextObj,
        initial_question: question.trim() || undefined,
      },
      {
        onSuccess: (newSess) => {
          setShowNewSessionModal(false);
          setNewSessionTitle("");
          setQuestion("");
          selectSession(newSess.session_id);
        },
      }
    );
  };

  const toggleArchiveSession = () => {
    if (!selectedSessionId || !activeSessionQuery.data) return;
    const current = activeSessionQuery.data.status;
    const nextStatus = current === "ACTIVE" ? "ARCHIVED" : "ACTIVE";
    updateSession.mutate({ sessionId: selectedSessionId, status: nextStatus });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    handleAsk(question);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAsk(question);
    }
  };

  const agentIds = useMemo(
    () => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])),
    [agents.data]
  );
  const versions = useMemo(
    () =>
      (agents.data?.agents ?? [])
        .filter((a) => a.agent_id === ctx.agent_id)
        .map((a) => a.agent_version),
    [agents.data, ctx.agent_id]
  );
  const setC = (k: keyof InvestigationContext) => (v: string) =>
    setCtx((c) => ({ ...c, [k]: v || undefined }));

  const activeSession = activeSessionQuery.data;
  const isPending = investigate.isPending || addTurn.isPending;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="AI Investigation Assistant & Session Memory"
        description="Conduct multi-turn investigations with persistent conversational memory in MongoDB, grounded lakehouse evidence, and structured analyst evaluation feedback."
      />

      {/* Top Session Control Strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-2 p-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">Investigation Mode:</span>
          {selectedSessionId && activeSession ? (
            <div className="flex items-center gap-2">
              <Badge tone={activeSession.status === "ACTIVE" ? "accent" : "neutral"}>
                {activeSession.status}
              </Badge>
              <span className="font-medium text-ink">{activeSession.title}</span>
              <span className="mono text-2xs text-muted">({activeSession.session_id})</span>
              <span className="rounded bg-surface px-1.5 py-0.5 text-2xs text-muted">
                {activeSession.turn_count} turns
              </span>
            </div>
          ) : (
            <span className="text-muted">Ad-Hoc Query Mode (Single turn)</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {selectedSessionId && activeSession && (
            <>
              <button
                type="button"
                className="btn btn-sm"
                onClick={toggleArchiveSession}
                disabled={updateSession.isPending}
              >
                {activeSession.status === "ACTIVE" ? "Archive Session" : "Re-open Session"}
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => selectSession(null)}
              >
                Exit Session
              </button>
            </>
          )}
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => setShowNewSessionModal(true)}
          >
            <span className="mr-1 font-bold">+</span> New Investigation Session
          </button>
        </div>
      </div>

      {unavailable && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
          <Icon name="alert" className="mt-0.5 shrink-0 text-warning-ink" />
          <div>
            <div className="font-medium text-ink">Assistant service not available</div>
            <div className="text-xs text-ink-2">
              The investigation endpoints (<span className="mono">/api/v1/investigations</span>) are not responding on this backend yet.
            </div>
          </div>
        </div>
      )}

      {/* New Session Modal */}
      {showNewSessionModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-lg p-5">
            <h3 className="text-base font-semibold text-ink">Create Investigation Session</h3>
            <p className="mt-1 text-xs text-ink-2">
              Start a multi-turn investigation session in MongoDB with preserved context and evaluation memory.
            </p>
            <form onSubmit={handleCreateSession} className="mt-4 flex flex-col gap-3">
              <Field label="Session Title">
                <input
                  className="input"
                  placeholder="e.g. Memory Leak in summarizer-1.2.0"
                  value={newSessionTitle}
                  onChange={(e) => setNewSessionTitle(e.target.value)}
                />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Analyst Username">
                  <input
                    className="input"
                    value={newSessionAnalyst}
                    onChange={(e) => setNewSessionAnalyst(e.target.value)}
                  />
                </Field>
                <Field label="Scope Agent">
                  <Select
                    value={ctx.agent_id ?? ""}
                    onChange={(v) => setCtx((c) => ({ ...c, agent_id: v || undefined }))}
                    options={agentIds}
                    placeholder="General System"
                  />
                </Field>
              </div>
              <Field label="Initial Question (Optional)">
                <textarea
                  className="input h-16 py-1 text-xs"
                  placeholder="Ask the opening question to immediately populate turn 1..."
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                />
              </Field>
              <div className="mt-2 flex justify-end gap-2">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setShowNewSessionModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-sm btn-primary"
                  disabled={createSession.isPending}
                >
                  {createSession.isPending ? "Creating…" : "Create Session"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        {/* Main Conversation Column */}
        <div className="flex min-w-0 flex-col gap-3">
          <Card bodyClassName="p-0">
            <div
              className="flex max-h-[64vh] min-h-[300px] flex-col gap-4 overflow-y-auto p-4"
              aria-live="polite"
            >
              {selectedSessionId && activeSession ? (
                // Multi-Turn Session View
                activeSession.turns?.length === 0 ? (
                  <div className="flex flex-col gap-3">
                    <EmptyState
                      title={`Session "${activeSession.title}" is ready`}
                    >
                      Ask your first question below to begin this multi-turn investigation.
                    </EmptyState>
                    <ExampleChips
                      examples={examples.data?.examples}
                      loading={examples.isLoading}
                      onPick={(q) => setQuestion(q)}
                    />
                  </div>
                ) : (
                  activeSession.turns.map((turn) => (
                    <SessionTurnView
                      key={turn.turn_id}
                      sessionId={selectedSessionId}
                      turn={turn}
                      onAsk={handleAsk}
                    />
                  ))
                )
              ) : localLog.length === 0 ? (
                // Single-Turn Empty State
                <div className="flex flex-col gap-3">
                  <EmptyState title="Ask a question or start an investigation session">
                    Select an existing session on the right or ask an ad-hoc question.
                  </EmptyState>
                  <ExampleChips
                    examples={examples.data?.examples}
                    loading={examples.isLoading}
                    onPick={(q) => setQuestion(q)}
                  />
                </div>
              ) : (
                // Single-Turn Local Log
                localLog.map((x) => <LocalExchangeView key={x.id} x={x} onAsk={handleAsk} />)
              )}
              {isPending && (
                <div role="status" className="flex items-center gap-2 rounded-lg border border-line bg-surface p-3 text-sm text-ink-2">
                  <span className="skeleton inline-block h-3 w-3 rounded-full" />
                  Retrieving lakehouse evidence and composing grounded response…
                </div>
              )}
              <div ref={bottom} />
            </div>
          </Card>

          {/* Input Box */}
          <form onSubmit={onSubmit} className="card flex flex-col gap-2 p-3">
            {activeCtx.length > 0 && (
              <div className="flex flex-wrap items-center gap-1 text-2xs text-ink-2">
                Context:
                {activeCtx.map(([k, v]) => (
                  <span key={k} className="mono rounded border border-line bg-surface-2 px-1.5 py-px">
                    {k}={String(v)}
                  </span>
                ))}
              </div>
            )}
            <label className="sr-only" htmlFor="question">
              Question
            </label>
            <textarea
              id="question"
              className="input h-20 resize-y py-2"
              placeholder={
                selectedSessionId
                  ? 'Ask follow-up question for this session (e.g. "What traces show the high latency?")...'
                  : 'Ask question or e.g. "Why did run R-… fail?"'
              }
              value={question}
              maxLength={1000}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={onKey}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-2xs text-muted">Enter to send · Shift+Enter for newline</span>
              <div className="flex items-center gap-2">
                {!selectedSessionId && question.trim() && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setShowNewSessionModal(true)}
                  >
                    Start Session with this Question
                  </button>
                )}
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={!question.trim() || isPending}
                >
                  {isPending ? "Investigating…" : selectedSessionId ? "Send Turn" : "Ask"}
                </button>
              </div>
            </div>
          </form>
        </div>

        {/* Right Sidebar */}
        <div className="flex flex-col gap-4">
          {/* MongoDB Evaluation Analytics Card */}
          <Card title="Evaluation & Memory Analytics" subtitle="MongoDB aggregation pipeline metrics">
            {sessionAnalytics.isLoading ? (
              <SkeletonRows rows={3} />
            ) : sessionAnalytics.data ? (
              <div className="flex flex-col gap-3 text-xs">
                <div className="grid grid-cols-2 gap-2 text-center">
                  <div className="rounded border border-line bg-surface-2 p-2">
                    <div className="text-2xs uppercase text-muted">Avg Rating</div>
                    <div className="text-lg font-bold text-ink">
                      {sessionAnalytics.data.avg_rating
                        ? `★ ${sessionAnalytics.data.avg_rating}`
                        : "N/A"}
                    </div>
                    <div className="text-3xs text-muted">
                      {sessionAnalytics.data.ratings_count} evaluated turns
                    </div>
                  </div>
                  <div className="rounded border border-line bg-surface-2 p-2">
                    <div className="text-2xs uppercase text-muted">Grounded Ratio</div>
                    <div className="text-lg font-bold text-good">
                      {Math.round(sessionAnalytics.data.grounded_ratio * 100)}%
                    </div>
                    <div className="text-3xs text-muted">tied to evidence</div>
                  </div>
                </div>

                <div className="flex justify-between border-t border-line pt-2 text-2xs text-ink-2">
                  <span>Total Sessions: <strong>{sessionAnalytics.data.total_sessions}</strong></span>
                  <span>Total Turns: <strong>{sessionAnalytics.data.total_turns}</strong></span>
                  <span>Avg Depth: <strong>{sessionAnalytics.data.avg_turns_per_session}</strong></span>
                </div>

                {Object.keys(sessionAnalytics.data.verdicts_breakdown || {}).length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(sessionAnalytics.data.verdicts_breakdown).map(([v, count]) => (
                      <span
                        key={v}
                        className={`rounded px-1.5 py-0.5 text-3xs font-medium ${
                          v === "accurate"
                            ? "bg-good/10 text-good"
                            : v === "hallucination"
                            ? "bg-critical/10 text-critical"
                            : "bg-warning/10 text-warning-ink"
                        }`}
                      >
                        {v}: {count}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </Card>

          {/* Investigation Sessions Selector */}
          <Card
            title="Investigation Sessions"
            subtitle="MongoDB multi-turn conversation memory"
            bodyClassName="p-3"
          >
            <div className="flex flex-col gap-2">
              <div className="flex gap-1.5">
                <input
                  className="input py-1 text-xs"
                  placeholder="Search sessions..."
                  value={sessionSearch}
                  onChange={(e) => setSessionSearch(e.target.value)}
                />
                <select
                  aria-label="Filter sessions by status"
                  className="input w-24 py-1 text-xs"
                  value={sessionStatusFilter}
                  onChange={(e) => setSessionStatusFilter(e.target.value)}
                >
                  <option value="">All</option>
                  <option value="ACTIVE">Active</option>
                  <option value="ARCHIVED">Archived</option>
                </select>
              </div>

              {sessionsQuery.isLoading ? (
                <SkeletonRows rows={3} />
              ) : sessionsQuery.data?.items?.length ? (
                <ul className="flex max-h-56 flex-col gap-1 overflow-auto">
                  {sessionsQuery.data.items.map((s: InvestigationSession) => {
                    const isSelected = s.session_id === selectedSessionId;
                    return (
                      <li key={s.session_id}>
                        <button
                          type="button"
                          className={`w-full rounded-md p-2 text-left text-xs transition ${
                            isSelected
                              ? "border border-accent bg-accent/10"
                              : "hover:bg-surface-2"
                          }`}
                          onClick={() => selectSession(s.session_id)}
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-ink truncate">{s.title}</span>
                            <Badge tone={s.status === "ACTIVE" ? "accent" : "neutral"}>
                              {s.status}
                            </Badge>
                          </div>
                          <div className="mt-1 flex items-center justify-between text-3xs text-muted">
                            <span className="mono">{s.session_id}</span>
                            <span>{s.turn_count} turns · {fmtDateTime(s.updated_at)}</span>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="text-xs text-muted">No sessions found.</div>
              )}
            </div>
          </Card>

          {/* Context Filter Card */}
          <Card title="Context" subtitle="Focus retrieval on a specific scope">
            <div className="flex flex-col gap-2">
              <Field label="Test run">
                <Select
                  value={ctx.test_run_id ?? ""}
                  onChange={setC("test_run_id")}
                  options={(testRuns.data?.test_runs ?? []).map((t) => ({
                    value: t.test_run_id,
                    label: `${t.test_run_name ?? ""} · ${t.test_run_id}`,
                  }))}
                  placeholder="None"
                />
              </Field>
              <Field label="Run id">
                <input
                  className="input mono"
                  placeholder="R-…"
                  value={ctx.run_id ?? ""}
                  onChange={(e) => setC("run_id")(e.target.value.trim())}
                />
              </Field>
              <Field label="Trace id">
                <input
                  className="input mono"
                  placeholder="32 hex chars"
                  value={ctx.trace_id ?? ""}
                  onChange={(e) => setC("trace_id")(e.target.value.trim())}
                />
              </Field>
              <Field label="Agent">
                <Select
                  value={ctx.agent_id ?? ""}
                  onChange={(v) =>
                    setCtx((c) => ({
                      ...c,
                      agent_id: v || undefined,
                      agent_version: undefined,
                      baseline_version: undefined,
                    }))
                  }
                  options={agentIds}
                  placeholder="None"
                />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Version">
                  <Select
                    value={ctx.agent_version ?? ""}
                    onChange={setC("agent_version")}
                    options={versions}
                    placeholder="—"
                    disabled={!ctx.agent_id}
                  />
                </Field>
                <Field label="Baseline version">
                  <Select
                    value={ctx.baseline_version ?? ""}
                    onChange={setC("baseline_version")}
                    options={versions}
                    placeholder="—"
                    disabled={!ctx.agent_id}
                  />
                </Field>
              </div>
              {activeCtx.length > 0 && (
                <button
                  type="button"
                  className="btn btn-sm self-start"
                  onClick={() => setCtx({})}
                >
                  Clear context
                </button>
              )}
            </div>
          </Card>

          {/* Legacy Relational History */}
          <Card title="Relational History" subtitle="PostgreSQL single-turn logs" bodyClassName="p-3">
            {history.isLoading ? (
              <SkeletonRows rows={2} />
            ) : history.data?.items?.length ? (
              <ul className="flex max-h-40 flex-col gap-1 overflow-auto">
                {history.data.items.slice(0, 5).map((h, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      className="w-full rounded px-2 py-1 text-left text-xs hover:bg-surface-2"
                      onClick={() => setQuestion(String(h.question ?? ""))}
                    >
                      <div className="line-clamp-1 text-ink">{String(h.question ?? "")}</div>
                      <div className="text-3xs text-muted">{h.created_at && fmtDateTime(String(h.created_at))}</div>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-xs text-muted">No relational history.</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Turn Component with Evaluation Feedback Form
// ---------------------------------------------------------------------------

function SessionTurnView({
  sessionId,
  turn,
  onAsk,
}: {
  sessionId: string;
  turn: InvestigationTurn;
  onAsk: (q: string) => void;
}) {
  const submitFeedback = useSubmitTurnFeedback();
  const [rating, setRating] = useState<number>(turn.feedback?.rating ?? 5);
  const [verdict, setVerdict] = useState<TurnVerdict>(turn.feedback?.verdict ?? "accurate");
  const [notes, setNotes] = useState<string>(turn.feedback?.notes ?? "");
  const [isEditing, setIsEditing] = useState(false);

  const handleFeedbackSubmit = (e: FormEvent) => {
    e.preventDefault();
    submitFeedback.mutate(
      {
        sessionId,
        turnId: turn.turn_id,
        rating,
        verdict,
        notes: notes || undefined,
        submittedBy: "analyst_sec",
      },
      {
        onSuccess: () => setIsEditing(false),
      }
    );
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Analyst Question */}
      <div className="ml-auto max-w-[85%] rounded-lg bg-accent/15 px-3 py-2 text-sm text-ink shadow-sm">
        <div className="flex items-center justify-between gap-2 border-b border-accent/20 pb-1 text-2xs text-ink-2">
          <span className="font-semibold">Turn #{turn.turn_id}</span>
          <span className="mono">{fmtDateTime(turn.created_at)}</span>
        </div>
        <div className="mt-1 font-medium">{turn.question}</div>
      </div>

      {/* Assistant Answer Card */}
      <div className="max-w-full rounded-lg border border-line bg-surface p-4 shadow-sm">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {turn.mode === "llm" ? (
              <Badge tone="warning" icon="assistant" title="Synthesized by language model">
                LLM Answer
              </Badge>
            ) : (
              <Badge tone="accent" icon="check" title="Template-grounded from lakehouse">
                {turn.mode || "Deterministic"}
              </Badge>
            )}
            {turn.grounded ? (
              <Badge tone="good">grounded in evidence</Badge>
            ) : (
              <Badge tone="critical">not grounded</Badge>
            )}
            {turn.intent && <span className="text-2xs text-muted">intent: {turn.intent}</span>}
          </div>

          <Markdown text={turn.answer} />

          {/* Evidence List */}
          {turn.evidence && turn.evidence.length > 0 && (
            <div>
              <div className="label mb-1">Evidence ({turn.evidence.length})</div>
              <ul className="flex flex-col gap-1">
                {turn.evidence.map((e, i) => {
                  const href = evidenceHref(e);
                  return (
                    <li
                      key={i}
                      className="flex flex-wrap items-baseline gap-2 rounded-md border border-line bg-surface-2 px-2 py-1.5 text-xs"
                    >
                      <Tag>{e.kind}</Tag>
                      {href ? (
                        <Link to={href} className="link font-medium">
                          {e.title || e.ref}
                        </Link>
                      ) : (
                        <span className="font-medium text-ink">{e.title || e.ref}</span>
                      )}
                      {e.ref && e.title && <span className="mono text-2xs text-muted">{e.ref}</span>}
                      {e.detail && <span className="basis-full text-ink-2">{e.detail}</span>}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* Suggested Follow-up Questions */}
          {turn.suggested_questions && turn.suggested_questions.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              <span className="text-2xs text-muted self-center">Follow up:</span>
              {turn.suggested_questions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onAsk(s)}
                  className="rounded-full border border-line-strong px-2.5 py-1 text-xs text-ink-2 hover:border-accent hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Evaluation Feedback Section */}
          <div className="mt-2 rounded-md border border-line bg-surface-2 p-2.5">
            {turn.feedback && !isEditing ? (
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-accent">
                    {"★".repeat(turn.feedback.rating)}{"☆".repeat(5 - turn.feedback.rating)}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-2xs font-semibold ${
                      turn.feedback.verdict === "accurate"
                        ? "bg-good/15 text-good"
                        : turn.feedback.verdict === "hallucination"
                        ? "bg-critical/15 text-critical"
                        : "bg-warning/15 text-warning-ink"
                    }`}
                  >
                    {turn.feedback.verdict}
                  </span>
                  {turn.feedback.notes && (
                    <span className="text-ink-2 italic">"{turn.feedback.notes}"</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-3xs text-muted">
                    Evaluated by {turn.feedback.submitted_by || "analyst"}
                  </span>
                  <button
                    type="button"
                    className="btn btn-xs"
                    onClick={() => setIsEditing(true)}
                  >
                    Edit
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleFeedbackSubmit} className="flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-ink">Analyst Evaluation</span>
                  <span className="text-3xs text-muted">Stored in MongoDB Turn Feedback</span>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  {/* Rating Stars */}
                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5].map((star) => (
                      <button
                        key={star}
                        type="button"
                        className={`text-sm ${
                          star <= rating ? "text-amber-500" : "text-muted"
                        }`}
                        onClick={() => setRating(star)}
                      >
                        ★
                      </button>
                    ))}
                    <span className="text-2xs text-muted">({rating}/5)</span>
                  </div>

                  {/* Verdict Dropdown */}
                  <select
                    aria-label="Verdict"
                    className="input py-0.5 text-xs"
                    value={verdict}
                    onChange={(e) => setVerdict(e.target.value as TurnVerdict)}
                  >
                    <option value="accurate">accurate</option>
                    <option value="incomplete">incomplete</option>
                    <option value="hallucination">hallucination</option>
                    <option value="irrelevant">irrelevant</option>
                    <option value="misleading">misleading</option>
                  </select>

                  {/* Notes Input */}
                  <input
                    className="input flex-1 py-0.5 text-xs"
                    placeholder="Evaluation notes (optional)..."
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />

                  <div className="flex gap-1">
                    {isEditing && (
                      <button
                        type="button"
                        className="btn btn-xs"
                        onClick={() => setIsEditing(false)}
                      >
                        Cancel
                      </button>
                    )}
                    <button
                      type="submit"
                      className="btn btn-xs btn-primary"
                      disabled={submitFeedback.isPending}
                    >
                      {submitFeedback.isPending ? "Saving…" : "Save Evaluation"}
                    </button>
                  </div>
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ad-hoc Single-turn Component (Backward compatible)
// ---------------------------------------------------------------------------

function LocalExchangeView({
  x,
  onAsk,
}: {
  x: LocalExchange;
  onAsk: (q: string) => void;
}) {
  const r = x.response;
  return (
    <div className="flex flex-col gap-2">
      <div className="ml-auto max-w-[85%] rounded-lg bg-accent/10 px-3 py-2 text-sm text-ink">
        {x.question}
        {Object.keys(x.context).length > 0 && (
          <div className="mono mt-1 text-2xs text-ink-2">
            {Object.entries(x.context)
              .map(([k, v]) => `${k}=${v}`)
              .join(" · ")}
          </div>
        )}
      </div>
      <div className="max-w-full rounded-lg border border-line bg-surface p-3">
        {x.pending ? (
          <div role="status" className="flex items-center gap-2 text-sm text-ink-2">
            <span className="skeleton inline-block h-3 w-3 rounded-full" /> Retrieving evidence and composing an answer…
          </div>
        ) : x.error ? (
          <ErrorPanel error={x.error} title="The assistant could not answer" onRetry={() => onAsk(x.question)} />
        ) : r ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {r.mode === "llm" ? (
                <Badge tone="warning" icon="assistant">LLM answer</Badge>
              ) : (
                <Badge tone="accent" icon="check">{r.mode}</Badge>
              )}
              {r.grounded ? <Badge tone="good">grounded in evidence</Badge> : <Badge tone="critical">not grounded</Badge>}
              {r.intent && <span className="text-2xs text-muted">intent: {r.intent}</span>}
            </div>
            <Markdown text={r.answer} />
            {r.evidence?.length > 0 && (
              <div>
                <div className="label mb-1">Evidence ({r.evidence.length})</div>
                <ul className="flex flex-col gap-1">
                  {r.evidence.map((e, i) => {
                    const href = evidenceHref(e);
                    return (
                      <li key={i} className="flex flex-wrap items-baseline gap-2 rounded-md border border-line px-2 py-1.5 text-xs">
                        <Tag>{e.kind}</Tag>
                        {href ? (
                          <Link to={href} className="link font-medium">{e.title || e.ref}</Link>
                        ) : (
                          <span className="font-medium text-ink">{e.title || e.ref}</span>
                        )}
                        {e.ref && e.title && <span className="mono text-2xs text-muted">{e.ref}</span>}
                        {e.detail && <span className="basis-full text-ink-2">{e.detail}</span>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ExampleChips({
  examples,
  loading,
  onPick,
}: {
  examples?: string[];
  loading: boolean;
  onPick: (q: string) => void;
}) {
  if (loading) return <SkeletonRows rows={1} />;
  if (!examples?.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="label">Example questions</div>
      <div className="flex flex-wrap gap-1.5">
        {examples.slice(0, 8).map((e) => (
          <button
            key={e}
            type="button"
            onClick={() => onPick(e)}
            className="rounded-full border border-line-strong px-2.5 py-1 text-left text-xs text-ink-2 hover:border-accent hover:text-ink"
          >
            {e}
          </button>
        ))}
      </div>
    </div>
  );
}

function evidenceHref(e: Evidence): string | null {
  const ref = (e.ref ?? "").trim();
  switch (e.kind) {
    case "trace":
    case "run":
      return idHref(ref) ?? appPath(`/runs/${encodeURIComponent(ref)}`);
    case "alert":
      return appPath(`/anomalies?alert=${encodeURIComponent(ref)}`);
    case "sql":
      return /^[a-z0-9_]+$/.test(ref) ? appPath(`/sql?q=${encodeURIComponent(ref)}`) : null;
    case "policy":
    case "finding":
      return appPath(`/security?tab=${e.kind === "policy" ? "policy" : "findings"}`);
    default:
      return idHref(ref);
  }
}
