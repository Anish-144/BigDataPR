import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTrace } from "../api/hooks";
import type { Evaluation, Span, Trace, TraceAlert, TraceFinding } from "../api/types";
import { Card, KeyValues, Note, PageHeader } from "../components/ui/Card";
import { ErrorPanel, EmptyState, LoadingBlock } from "../components/ui/states";
import { Badge, SeverityBadge, StatusBadge, SuccessBadge, Tag } from "../components/ui/Badge";
import { DataTable, Tabs, type Column } from "../components/ui/DataTable";
import { Icon } from "../components/ui/Icon";
import { Waterfall, buildRows, kindColor, spanProblem } from "../components/trace/Waterfall";
import { fmtDateTime, fmtInt, fmtMs, fmtNum, fmtUsd } from "../lib/format";

export default function TraceView() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const q = useTrace(traceId);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" className="btn btn-sm" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/app/runs"))}>
          <Icon name="chevronLeft" size={14} /> Back
        </button>
        <Link to="/app/runs" className="link">
          Run Explorer
        </Link>
        <span className="text-muted">/</span>
        <span className="mono text-ink-2">{traceId}</span>
        {q.data?.run && (
          <Link
            className="btn btn-sm ml-auto"
            to={`/app/assistant?run_id=${encodeURIComponent(q.data.run.run_id)}&trace_id=${encodeURIComponent(q.data.trace_id)}&agent_id=${encodeURIComponent(q.data.run.agent_id)}&agent_version=${encodeURIComponent(q.data.run.agent_version)}&q=${encodeURIComponent(`Why did run ${q.data.run.run_id} ${q.data.run.task_success ? "behave this way" : "fail"}?`)}`}
          >
            <Icon name="assistant" size={14} /> Ask the assistant about this run
          </Link>
        )}
      </div>
      {q.isLoading ? (
        <LoadingBlock height={420} label="Loading trace…" />
      ) : q.isError ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} title="Could not load this trace" />
      ) : q.data ? (
        <TraceBody trace={q.data} />
      ) : null}
    </div>
  );
}

function TraceBody({ trace }: { trace: Trace }) {
  const run = trace.run;
  const { rows } = useMemo(() => buildRows(trace.spans), [trace.spans]);
  const firstProblem = rows.find((r) => spanProblem(r.span))?.span.span_id;
  const [selected, setSelected] = useState<string | null>(firstProblem ?? rows[0]?.span.span_id ?? null);
  const [tab, setTab] = useState<"evals" | "findings" | "alerts" | "run">(trace.security_findings.length ? "findings" : "evals");
  useEffect(() => {
    setSelected(firstProblem ?? rows[0]?.span.span_id ?? null);
  }, [trace.trace_id]); // eslint-disable-line react-hooks/exhaustive-deps
  const span = trace.spans.find((s) => s.span_id === selected) ?? null;
  const t0 = rows.length ? Math.min(...trace.spans.map((s) => new Date(s.start_time).getTime())) : 0;
  const problems = rows.filter((r) => spanProblem(r.span)).length;

  return (
    <>
      <PageHeader
        title={run ? `Run ${run.run_id}` : `Trace ${trace.trace_id}`}
        description={
          run ? (
            <span className="flex flex-wrap items-center gap-2">
              <span>
                {run.agent_name ?? run.agent_id} <span className="mono">{run.agent_version}</span> · {run.model_name} · prompt {String(run.prompt_version ?? "—")} ·{" "}
                {run.workload_type} · {run.difficulty}
              </span>
              <StatusBadge status={run.status} />
              <SuccessBadge success={run.task_success} />
              {run.error_category && <Badge tone="critical">{run.error_category}</Badge>}
            </span>
          ) : (
            "Run summary not found for this trace (spans only)."
          )
        }
      />
      {run && (
        <div className="bg-surface rounded-2xl border border-line p-5 shadow-sm mb-2">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-8">
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest flex justify-between">Latency <Tag>simulated</Tag></span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtMs(run.latency_ms)}</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">TTFT</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtMs(run.ttft_ms)}</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">Tokens</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtInt(run.total_tokens)}</span>
              <span className="text-[10px] font-semibold text-muted uppercase">{fmtInt(run.input_tokens)} in · {fmtInt(run.output_tokens)} out</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">Est. Cost</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtUsd(run.estimated_cost_usd)}</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">Spans</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtInt(trace.spans.length)}</span>
              <span className={`text-[10px] font-bold uppercase ${problems > 0 ? 'text-critical-ink' : 'text-muted'}`}>{problems} problems</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">Tools</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtInt(run.tool_calls)}</span>
              <span className={`text-[10px] font-bold uppercase ${run.tool_errors > 0 ? 'text-warning-ink' : 'text-muted'}`}>{fmtInt(run.tool_errors)} errs</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">Retries</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtInt(run.retries)}</span>
            </div>
            <div className="flex flex-col gap-1 pr-4 border-r border-line-strong/30 last:border-0">
              <span className="text-[11px] font-bold text-ink-2 uppercase tracking-widest">Denials</span>
              <span className="text-xl font-extrabold text-ink tracking-tight mt-1">{fmtInt(run.policy_denials)}</span>
            </div>
          </div>
        </div>
      )}
      {run && (run.injected_faults?.length ?? 0) > 0 && (
        <Note tone="warn">
          This run had injected faults: <strong>{run.injected_faults!.join(", ")}</strong>. These are ground-truth labels from the workload simulator, used to measure
          detector precision/recall - they are not visible to the detectors.
        </Note>
      )}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="bg-surface rounded-2xl border border-line shadow-sm overflow-hidden flex flex-col">
          <div className="border-b border-line px-5 py-4">
             <h2 className="text-base font-bold text-ink tracking-tight">Trace Waterfall</h2>
             <div className="text-[13px] text-ink-2 mt-0.5">{trace.spans.length} spans · trace {trace.trace_id}</div>
          </div>
          <div className="p-4 overflow-hidden">
            {trace.spans.length ? <Waterfall spans={trace.spans} selectedId={selected} onSelect={setSelected} /> : <EmptyState title="No spans" />}
          </div>
        </div>
        <SpanPanel span={span} t0={t0} findings={trace.security_findings.filter((f) => f.span_id && f.span_id === span?.span_id)} />
      </div>
      <Card bodyClassName="p-0">
        <div className="px-4 pt-2">
          <Tabs
            label="Trace details"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "evals", label: `Evaluations (${trace.evaluations.length})` },
              { id: "findings", label: `Security findings (${trace.security_findings.length})` },
              { id: "alerts", label: `Anomaly alerts (${trace.anomaly_alerts.length})` },
              { id: "run", label: "Run record" },
            ]}
          />
        </div>
        <div className="p-4">
          {tab === "evals" && <EvalTable evals={trace.evaluations} />}
          {tab === "findings" && <FindingsList findings={trace.security_findings} onSpan={setSelected} />}
          {tab === "alerts" && <AlertsList alerts={trace.anomaly_alerts} />}
          {tab === "run" &&
            (run ? (
              <KeyValues
                cols={3}
                items={Object.entries(run).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") || "—" : v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)] as [string, ReactNode])}
              />
            ) : (
              <EmptyState title="No run record for this trace" />
            ))}
        </div>
      </Card>
    </>
  );
}

function SpanPanel({ span, t0, findings }: { span: Span | null; t0: number; findings: TraceFinding[] }) {
  if (!span) return <Card title="Span details">{<EmptyState title="Select a span" />}</Card>;
  const problem = spanProblem(span);
  const items: [string, ReactNode][] = [
    ["kind", <span key="k" className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: kindColor(span.span_kind) }} />{span.span_kind}</span>],
    ["status", <StatusBadge key="s" status={span.status} />],
    ["start offset", `+${fmtMs(new Date(span.start_time).getTime() - t0)}`],
    ["duration", fmtMs(span.duration_ms)],
  ];
  const add = (k: string, v: unknown, f?: (v: never) => ReactNode) => {
    if (v === null || v === undefined || (Array.isArray(v) && !v.length)) return;
    items.push([k, f ? f(v as never) : typeof v === "boolean" ? (v ? "true" : "false") : String(v)]);
  };
  add("error category", span.error_category);
  add("attempt", span.attempt);
  add("depth", span.depth);
  add("step index", span.step_index);
  add("model", span.model_name);
  add("input tokens", span.input_tokens, (v: number) => fmtInt(v));
  add("output tokens", span.output_tokens, (v: number) => fmtInt(v));
  add("ttft", span.ttft_ms, (v: number) => fmtMs(v));
  add("tool", span.tool_name);
  add("tool args valid", span.tool_args_valid);
  add("tool allowed", span.tool_allowed);
  add("policy decision", span.policy_decision, (v: string) => (v === "deny" ? <Badge tone="critical">deny</Badge> : v === "flag" ? <Badge tone="warning">flag</Badge> : v));
  add("data classification", span.data_classification);
  add("top k", span.top_k);
  add("delegated agent", span.delegated_agent_id);
  add("dq flags", span.dq_flags, (v: string[]) => v.join(", "));
  add("span id", span.span_id, (v: string) => <span className="mono">{v}</span>);
  add("parent span", span.parent_span_id, (v: string) => <span className="mono">{v}</span>);
  return (
    <Card title={span.span_name} subtitle={problem ? <span className="font-medium text-critical-ink">Marked: {problem.label}</span> : "Span attributes"}>
      <div className="flex flex-col gap-3">
        <KeyValues cols={1} items={items} />
        {span.retrieved_doc_ids && span.retrieved_doc_ids.length > 0 && (
          <div>
            <div className="label mb-1">Retrieved documents (rank · id · score)</div>
            <ol className="flex flex-col gap-0.5 text-xs">
              {span.retrieved_doc_ids.map((d, i) => (
                <li key={d + i} className="num flex justify-between gap-2 border-b border-line/60 py-0.5">
                  <span className="text-ink-2">#{i + 1}</span>
                  <span className="mono flex-1 text-ink">{d}</span>
                  <span className="text-ink-2">{fmtNum(span.retrieval_scores?.[i], 4)}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {span.attributes && Object.keys(span.attributes).length > 0 && (
          <div>
            <div className="label mb-1">Attributes</div>
            <pre className="mono max-h-40 overflow-auto rounded border border-line bg-surface-2 p-2 text-ink-2">{JSON.stringify(span.attributes, null, 2)}</pre>
          </div>
        )}
        {findings.length > 0 && (
          <div>
            <div className="label mb-1">Security findings on this span</div>
            <ul className="flex flex-col gap-1">
              {findings.map((f) => (
                <li key={f.finding_id} className="rounded border border-line p-2 text-xs">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={f.severity} />
                    <span className="font-medium text-ink">{f.rule_id}</span> <span className="text-ink-2">{f.rule_name}</span>
                  </div>
                  <div className="mt-1 break-words text-ink-2">{f.evidence}</div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function EvalTable({ evals }: { evals: Evaluation[] }) {
  if (!evals.length) return <EmptyState title="No evaluation records for this trace" />;
  const cols: Column<Evaluation>[] = [
    { key: "metric_name", header: "Metric", render: (e) => <span className="font-medium">{e.metric_name}</span> },
    { key: "score", header: "Score", align: "right", render: (e) => fmtNum(e.score, 3) },
    { key: "threshold", header: "Threshold", align: "right", render: (e) => fmtNum(e.threshold, 3) },
    { key: "passed", header: "Result", render: (e) => (e.passed === null ? <Badge>info only</Badge> : e.passed ? <Badge tone="good">pass</Badge> : <Badge tone="critical">fail</Badge>) },
    {
      key: "evaluator_type",
      header: "Evaluator",
      render: (e) => (
        <span className="flex flex-wrap items-center gap-1">
          <span>{e.evaluator_name}</span>
          <span className="text-muted">v{e.evaluator_version}</span>
          {e.evaluator_type === "deterministic" ? <Tag title="Rule/reference-based check">deterministic</Tag> : <Badge tone="warning" title="Probabilistic model judgment - not ground truth">model-judged</Badge>}
        </span>
      ),
    },
    { key: "rubric", header: "Rubric", className: "max-w-[280px] text-ink-2" },
    { key: "evidence", header: "Evidence", className: "mono max-w-[280px] break-words text-ink-2" },
  ];
  return <DataTable columns={cols} rows={evals} rowKey={(e) => `${e.evaluator_name}:${e.metric_name}`} dense maxHeight={420} />;
}

function FindingsList({ findings, onSpan }: { findings: TraceFinding[]; onSpan: (id: string) => void }) {
  if (!findings.length) return <EmptyState title="No security findings for this trace" icon="check" />;
  return (
    <div className="flex flex-col gap-2">
      <Note>Findings come from deterministic policy rules applied to synthetic data. A finding is evidence to investigate, not proof of malicious intent.</Note>
      {findings.map((f) => (
        <div key={f.finding_id} className="rounded-md border border-line p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={f.severity} />
            <span className="font-semibold text-ink">{f.rule_id}</span>
            <span className="text-ink">{f.rule_name}</span>
            <Badge tone={f.action === "blocked" ? "accent" : "neutral"} icon={f.action === "blocked" ? "stop" : "flag"}>
              {f.action}
            </Badge>
            <span className="text-muted">
              {f.detector} · policy {f.policy_version} · {fmtDateTime(f.event_time)}
            </span>
          </div>
          <div className="mt-1.5 break-words text-ink-2">{f.evidence}</div>
          {f.span_id && (
            <button type="button" className="link mt-1 text-xs" onClick={() => onSpan(f.span_id!)}>
              Show span {f.tool_name ? `(${f.tool_name})` : ""} in waterfall
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function AlertsList({ alerts }: { alerts: TraceAlert[] }) {
  if (!alerts.length) return <EmptyState title="No anomaly alerts reference this trace" icon="check" />;
  return (
    <div className="flex flex-col gap-2">
      <Note>An anomaly is an unusual execution pattern worth reviewing - a signal, not proof of a bug or an attack.</Note>
      {alerts.map((a) => (
        <div key={a.alert_id} className="rounded-md border border-line p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={a.severity} />
            <span className="font-semibold text-ink">{a.anomaly_type}</span>
            <span className="text-ink-2">{a.detector}</span>
            <span className="num text-muted">score {fmtNum(a.score, 3)}</span>
            <Link className="link ml-auto" to={`/app/anomalies?alert=${encodeURIComponent(a.alert_id)}`}>
              Open in Anomaly Center
            </Link>
          </div>
          <div className="mt-1.5 text-ink">{a.explanation}</div>
          {a.supporting_metrics && (
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-ink-2">
              {Object.entries(a.supporting_metrics).map(([k, v]) => (
                <span key={k} className="num">
                  {k}: <span className="text-ink">{fmtNum(v, 3)}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
