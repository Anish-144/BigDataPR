import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAgents, useInvestigate, useInvestigationExamples, useInvestigationHistory, useTestRuns } from "../api/hooks";
import type { Evidence, InvestigationContext, InvestigationResponse } from "../api/types";
import { Card, Field, Note, PageHeader } from "../components/ui/Card";
import { Select } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, SkeletonRows } from "../components/ui/states";
import { Badge, Tag } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { Markdown, idHref } from "../lib/markdown";
import { appPath } from "../lib/nav";
import { fmtDateTime } from "../lib/format";

interface Exchange {
  id: number;
  question: string;
  context: InvestigationContext;
  response?: InvestigationResponse;
  error?: unknown;
  pending: boolean;
  fromHistory?: boolean;
}

const CTX_KEYS: (keyof InvestigationContext)[] = ["test_run_id", "run_id", "trace_id", "agent_id", "agent_version", "baseline_version"];

const isUnavailable = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 501 || e.status === 503 || e.status === 0);

export default function Assistant() {
  const [sp] = useSearchParams();
  const examples = useInvestigationExamples();
  const history = useInvestigationHistory(20);
  const investigate = useInvestigate();
  const agents = useAgents();
  const testRuns = useTestRuns(100);
  const [question, setQuestion] = useState(sp.get("q") ?? "");
  const [ctx, setCtx] = useState<InvestigationContext>(() => {
    const c: InvestigationContext = {};
    for (const k of CTX_KEYS) {
      const v = sp.get(k);
      if (v) c[k] = v;
    }
    return c;
  });
  const [log, setLog] = useState<Exchange[]>([]);
  const nextId = useRef(1);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [log.length]);

  const unavailable = (examples.isError && isUnavailable(examples.error)) || log.some((x) => x.error && isUnavailable(x.error));

  const ask = (q: string) => {
    const text = q.trim();
    if (!text || investigate.isPending) return;
    const id = nextId.current++;
    const context: InvestigationContext = Object.fromEntries(Object.entries(ctx).filter(([, v]) => v)) as InvestigationContext;
    setLog((l) => [...l, { id, question: text, context, pending: true }]);
    setQuestion("");
    investigate.mutate(
      { question: text, context },
      {
        onSuccess: (response) => setLog((l) => l.map((x) => (x.id === id ? { ...x, response, pending: false } : x))),
        onError: (error) => setLog((l) => l.map((x) => (x.id === id ? { ...x, error, pending: false } : x))),
      },
    );
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    ask(question);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask(question);
    }
  };

  const agentIds = useMemo(() => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])), [agents.data]);
  const versions = useMemo(() => (agents.data?.agents ?? []).filter((a) => a.agent_id === ctx.agent_id).map((a) => a.agent_version), [agents.data, ctx.agent_id]);
  const setC = (k: keyof InvestigationContext) => (v: string) => setCtx((c) => ({ ...c, [k]: v || undefined }));
  const activeCtx = Object.entries(ctx).filter(([, v]) => v);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="AI Investigation Assistant"
        description="Ask questions about runs, versions, regressions, anomalies and policy findings. Answers are grounded in lakehouse aggregates, trace summaries, evaluation records, policy definitions and local knowledge documents, with evidence links."
      />
      <Note>
        The assistant only uses fixed, parameterised read-only query tools - it cannot run arbitrary SQL or change anything. A <Tag>deterministic</Tag> answer is
        template-generated from retrieved evidence; an <Tag>llm</Tag> answer is model-written and may be imperfect - always check the evidence. Recommendations need human
        approval.
      </Note>
      {unavailable && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
          <Icon name="alert" className="mt-0.5 shrink-0 text-warning-ink" />
          <div>
            <div className="font-medium text-ink">Assistant service not available</div>
            <div className="text-xs text-ink-2">
              The investigation endpoints (<span className="mono">/api/v1/investigations</span>) are not responding on this backend yet
              {examples.error instanceof ApiError ? ` (HTTP ${examples.error.status})` : ""}. The rest of the dashboard is unaffected; try again once the service is deployed.
            </div>
            <button type="button" className="btn btn-sm mt-2" onClick={() => { examples.refetch(); history.refetch(); }}>
              <Icon name="refresh" size={13} /> Check again
            </button>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-3">
          <Card bodyClassName="p-0">
            <div className="flex max-h-[62vh] min-h-[260px] flex-col gap-4 overflow-y-auto p-4" aria-live="polite">
              {log.length === 0 ? (
                <div className="flex flex-col gap-3">
                  <EmptyState title="Ask a question to start an investigation">
                    Set optional context on the right (a test run, run, trace or agent version) to focus the answer.
                  </EmptyState>
                  <ExampleChips examples={examples.data?.examples} loading={examples.isLoading} onPick={(q) => setQuestion(q)} />
                </div>
              ) : (
                log.map((x) => <ExchangeView key={x.id} x={x} onAsk={ask} />)
              )}
              <div ref={bottom} />
            </div>
          </Card>
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
              placeholder='e.g. "Why did run R-… fail?" or "Compare qa-assistant 1.0.0 and 1.1.0"'
              value={question}
              maxLength={1000}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={onKey}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-2xs text-muted">Enter to ask · Shift+Enter for a new line</span>
              <button type="submit" className="btn btn-primary" disabled={!question.trim() || investigate.isPending}>
                {investigate.isPending ? "Investigating…" : "Ask"}
              </button>
            </div>
            {log.length > 0 && <ExampleChips examples={examples.data?.examples} loading={false} onPick={(q) => setQuestion(q)} compact />}
          </form>
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Context" subtitle="Optional - focuses retrieval on a specific scope">
            <div className="flex flex-col gap-2">
              <Field label="Test run">
                <Select
                  value={ctx.test_run_id ?? ""}
                  onChange={setC("test_run_id")}
                  options={(testRuns.data?.test_runs ?? []).map((t) => ({ value: t.test_run_id, label: `${t.test_run_name ?? ""} · ${t.test_run_id}` }))}
                  placeholder="None"
                />
              </Field>
              <Field label="Run id">
                <input className="input mono" placeholder="R-…" value={ctx.run_id ?? ""} onChange={(e) => setC("run_id")(e.target.value.trim())} />
              </Field>
              <Field label="Trace id">
                <input className="input mono" placeholder="32 hex chars" value={ctx.trace_id ?? ""} onChange={(e) => setC("trace_id")(e.target.value.trim())} />
              </Field>
              <Field label="Agent">
                <Select value={ctx.agent_id ?? ""} onChange={(v) => setCtx((c) => ({ ...c, agent_id: v || undefined, agent_version: undefined, baseline_version: undefined }))} options={agentIds} placeholder="None" />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Version">
                  <Select value={ctx.agent_version ?? ""} onChange={setC("agent_version")} options={versions} placeholder="—" disabled={!ctx.agent_id} />
                </Field>
                <Field label="Baseline version">
                  <Select value={ctx.baseline_version ?? ""} onChange={setC("baseline_version")} options={versions} placeholder="—" disabled={!ctx.agent_id} />
                </Field>
              </div>
              {activeCtx.length > 0 && (
                <button type="button" className="btn btn-sm self-start" onClick={() => setCtx({})}>
                  Clear context
                </button>
              )}
            </div>
          </Card>
          <Card title="Recent investigations" bodyClassName="p-3">
            {history.isLoading ? (
              <SkeletonRows rows={3} />
            ) : history.isError ? (
              isUnavailable(history.error) ? (
                <div className="text-xs text-muted">History unavailable (service not deployed).</div>
              ) : (
                <ErrorPanel error={history.error} onRetry={() => history.refetch()} />
              )
            ) : history.data?.items.length ? (
              <ul className="flex max-h-80 flex-col gap-1 overflow-auto">
                {history.data.items.map((h, i) => (
                  <li key={i}>
                    <button type="button" className="w-full rounded-md px-2 py-1.5 text-left text-xs hover:bg-surface-2" onClick={() => setQuestion(String(h.question ?? ""))} title="Put this question in the box">
                      <div className="line-clamp-2 text-ink">{String(h.question ?? "(no question)")}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1 text-2xs text-muted">
                        {h.mode && <Tag>{String(h.mode)}</Tag>}
                        {h.grounded === false && <Badge tone="warning">not grounded</Badge>}
                        {h.intent && <span>{String(h.intent)}</span>}
                        {h.created_at && <span>· {fmtDateTime(String(h.created_at))}</span>}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-xs text-muted">No investigations yet.</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function ExampleChips({ examples, loading, onPick, compact }: { examples?: string[]; loading: boolean; onPick: (q: string) => void; compact?: boolean }) {
  if (loading) return <SkeletonRows rows={1} />;
  if (!examples?.length) return null;
  return (
    <div className="flex flex-col gap-1.5">
      {!compact && <div className="label">Example questions</div>}
      <div className="flex flex-wrap gap-1.5">
        {examples.slice(0, compact ? 4 : 12).map((e) => (
          <button key={e} type="button" onClick={() => onPick(e)} className="rounded-full border border-line-strong px-2.5 py-1 text-left text-xs text-ink-2 hover:border-accent hover:text-ink">
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

function ExchangeView({ x, onAsk }: { x: Exchange; onAsk: (q: string) => void }) {
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
          isUnavailable(x.error) ? (
            <ErrorPanel error={x.error} title="Assistant service not available" />
          ) : (
            <ErrorPanel error={x.error} title="The assistant could not answer" onRetry={() => onAsk(x.question)} />
          )
        ) : r ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {r.mode === "llm" ? (
                <Badge tone="warning" icon="assistant" title="Written by a language model from retrieved evidence - may contain mistakes">
                  LLM answer
                </Badge>
              ) : (
                <Badge tone="accent" icon="check" title="Template-generated from retrieved evidence, no model involved">
                  {r.mode === "deterministic" ? "Deterministic answer" : r.mode}
                </Badge>
              )}
              {r.grounded ? <Badge tone="good">grounded in evidence</Badge> : <Badge tone="critical">not grounded</Badge>}
              {r.intent && <span className="text-2xs text-muted">intent: {r.intent}</span>}
            </div>
            {!r.grounded && (
              <Note tone="warn">
                This answer is <strong>not grounded</strong>: the assistant could not tie it to retrieved evidence. Treat it as unverified and check the data directly.
              </Note>
            )}
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
            {r.limitations && (
              <div className="text-xs text-ink-2">
                <span className="font-medium text-ink">Limitations: </span>
                {r.limitations}
              </div>
            )}
            {r.suggested_questions?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {r.suggested_questions.map((s) => (
                  <button key={s} type="button" onClick={() => onAsk(s)} className="rounded-full border border-line-strong px-2.5 py-1 text-xs text-ink-2 hover:border-accent hover:text-ink">
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
