import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAgents, useAnomalies, useAnomaly, useAnomalyFeedback, useAnomalySummary, type AnomalyFilters } from "../api/hooks";
import type { AnomalyRow, AnomalySummary, Confusion, Row } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, Field, KeyValues, Note, PageHeader } from "../components/ui/Card";
import { DataTable, Pagination, Select, type Column } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, LoadingBlock, SkeletonRows } from "../components/ui/states";
import { Badge, SeverityBadge, Tag } from "../components/ui/Badge";
import { ChartFrame, SERIES } from "../components/charts/ChartFrame";
import { BarsChart } from "../components/charts/Charts";
import { fmtDateTime, fmtInt, fmtNum, fmtPct, fmtMs } from "../lib/format";

const LIMIT = 25;

export default function Anomalies() {
  const { days } = useDays();
  const summary = useAnomalySummary(days);
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Anomaly Center"
        description="Alerts from rule-based detectors and an Isolation Forest model over agent runs, with explanations, supporting metrics and analyst feedback."
      />
      <Note tone="warn">
        {summary.data?.note ??
          "An anomaly is an unusual execution pattern worth investigating. It is not automatically a bug or an attack; detectors have measured false-positive rates."}{" "}
        Feedback is stored for detector review and is never auto-applied.
      </Note>
      {summary.isLoading ? (
        <LoadingBlock height={300} />
      ) : summary.isError && !summary.data ? (
        <ErrorPanel error={summary.error} onRetry={() => summary.refetch()} title="Could not load anomaly summary" />
      ) : summary.data ? (
        <>
          <DetectorEvaluation s={summary.data} />
          <SummaryPanels s={summary.data} />
        </>
      ) : null}
      <AlertsBrowser summary={summary.data} />
    </div>
  );
}

function ConfusionTile({ name, c, extra }: { name: string; c?: Confusion; extra?: string }) {
  if (!c) return null;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-line p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-ink">{name}</span>
        {extra && <span className="text-2xs text-muted">{extra}</span>}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {(
          [
            ["Precision", c.precision],
            ["Recall", c.recall],
            ["F1", c.f1],
          ] as const
        ).map(([k, v]) => (
          <div key={k}>
            <div className="text-2xs text-ink-2">{k}</div>
            <div className="text-xl font-semibold text-ink">{fmtPct(v, 1)}</div>
          </div>
        ))}
      </div>
      <div className="num flex flex-wrap gap-x-3 text-2xs text-ink-2">
        <span>TP {fmtInt(c.tp)}</span>
        <span>FP {fmtInt(c.fp)}</span>
        <span>FN {fmtInt(c.fn)}</span>
        <span>TN {fmtInt(c.tn)}</span>
        <span>FPR {fmtPct(c.false_positive_rate, 2)}</span>
      </div>
    </div>
  );
}

function DetectorEvaluation({ s }: { s: AnomalySummary }) {
  const ev = s.detector_evaluation;
  if (!ev) {
    return (
      <Card title="Detector evaluation">
        <EmptyState title="No detector evaluation recorded yet">Run the holdout evaluation job to measure precision/recall.</EmptyState>
      </Card>
    );
  }
  const faults = Object.entries(ev.per_fault_recall ?? {}).map(([fault, v]) => ({ fault, ...v }) as Row);
  const fseries = [
    { key: "rules", label: "Rules", color: SERIES[0] },
    { key: "isolation_forest", label: "Isolation Forest", color: SERIES[1] },
    { key: "combined", label: "Combined", color: SERIES[2] },
  ];
  const ops = Object.entries(ev.isolation_forest_operating_points ?? {}).map(([q, v]) => ({ quantile: q, ...v }) as Row);
  const clean = ev.clean_traffic;
  const m = s.model;
  return (
    <Card
      title="Detector evaluation on a held-out set"
      subtitle={
        <>
          Scenario <span className="mono">{ev.eval_scenario ?? "—"}</span> · {fmtInt(ev.eval_runs)} runs · {fmtInt(ev.positives)} labelled positives (injected faults) · model{" "}
          <span className="mono">{ev.model_version ?? "—"}</span> · recorded {fmtDateTime(ev.recorded_at)}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          <ConfusionTile name="Rule detectors" c={ev.overall?.rules} />
          <ConfusionTile name="Isolation Forest" c={ev.overall?.isolation_forest} extra={ev.isolation_forest_roc_auc != null ? `ROC AUC ${fmtNum(ev.isolation_forest_roc_auc, 3)}` : undefined} />
          <ConfusionTile name="Combined" c={ev.overall?.combined} />
        </div>
        <Note tone="warn">
          <strong>Limitations.</strong> Precision and recall are measured against synthetic injected-fault labels on a holdout scenario the model was not trained on
          {ev.model_training_scenarios?.length ? ` (training: ${ev.model_training_scenarios.join(", ")})` : ""}. Real traffic will differ.
          {clean ? (
            <>
              {" "}
              On clean traffic ({clean.scenario}, {fmtInt(clean.runs)} runs) the Isolation Forest still flagged {fmtPct(clean.isolation_forest_flag_rate, 2)} and the rules{" "}
              {fmtPct(clean.rules_flag_rate, 2)} of runs - expect false positives and confirm each alert in its trace.
            </>
          ) : null}{" "}
          Some fault types are weakly detected (see per-fault recall).
        </Note>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <ChartFrame
            title="Recall per injected fault type"
            subtitle="Share of labelled runs of each fault that raised at least one alert"
            legend={fseries.map((f) => ({ label: f.label, color: f.color }))}
            table={{
              columns: [
                { key: "fault", header: "Fault" },
                { key: "runs", header: "Runs", align: "right", render: (r: Row) => fmtInt(r.runs) },
                { key: "rules", header: "Rules", align: "right", render: (r: Row) => fmtPct(r.rules, 1) },
                { key: "isolation_forest", header: "Isolation Forest", align: "right", render: (r: Row) => fmtPct(r.isolation_forest, 1) },
                { key: "combined", header: "Combined", align: "right", render: (r: Row) => fmtPct(r.combined, 1) },
              ],
              rows: faults,
            }}
          >
            {faults.length ? <BarsChart data={faults} categoryKey="fault" series={fseries} horizontal valueFormat={(v) => fmtPct(v, 0)} valueDomain={[0, 1]} /> : <EmptyState title="No per-fault data" />}
          </ChartFrame>
          <div className="flex flex-col gap-4">
            <Card title="Isolation Forest operating points" subtitle="Score threshold at each training-score quantile (no labels used to choose it)" bodyClassName="p-3">
              {ops.length ? (
                <DataTable
                  dense
                  maxHeight="none"
                  rows={ops}
                  rowKey={(r) => String(r.quantile)}
                  columns={[
                    { key: "quantile", header: "Quantile", render: (r) => <span className="mono">{String(r.quantile)}{Number(r.threshold) === Number(m?.threshold) ? " (active)" : ""}</span> },
                    { key: "threshold", header: "Threshold", align: "right", render: (r) => fmtNum(r.threshold, 3) },
                    { key: "precision", header: "Precision", align: "right", render: (r) => fmtPct(r.precision, 1) },
                    { key: "recall", header: "Recall", align: "right", render: (r) => fmtPct(r.recall, 1) },
                    { key: "f1", header: "F1", align: "right", render: (r) => fmtPct(r.f1, 1) },
                    { key: "false_positive_rate", header: "FPR", align: "right", render: (r) => fmtPct(r.false_positive_rate, 2) },
                  ]}
                />
              ) : (
                <EmptyState title="No operating points" />
              )}
            </Card>
            {ev.incident_windows?.incidents?.length ? (
              <Card title="Incident windows (window-level regression rule)" bodyClassName="p-3">
                <DataTable
                  dense
                  maxHeight="none"
                  rows={ev.incident_windows.incidents as unknown as Row[]}
                  rowKey={(r) => String(r.incident)}
                  columns={[
                    { key: "incident", header: "Incident" },
                    { key: "agent", header: "Agent" },
                    { key: "runs", header: "Runs", align: "right", render: (r) => fmtInt(r.runs) },
                    { key: "detected_by_window_rule", header: "Detected", render: (r) => (r.detected_by_window_rule ? <Badge tone="good">yes</Badge> : <Badge tone="critical">missed</Badge>) },
                    { key: "window_alerts", header: "Window alerts", align: "right", render: (r) => fmtInt(r.window_alerts) },
                  ]}
                />
              </Card>
            ) : null}
          </div>
        </div>
        {m && (
          <details className="rounded-md border border-line p-3 text-xs">
            <summary className="cursor-pointer font-medium text-ink">Model details: {m.algorithm ?? "model"} · {m.model_version}</summary>
            <div className="mt-2">
              <KeyValues
                items={[
                  ["trained at", fmtDateTime(m.trained_at)],
                  ["training runs", fmtInt(m.training?.runs)],
                  ["training scenarios", (m.training?.scenarios ?? []).join(", ") || "—"],
                  ["agent versions", fmtInt(m.training?.agent_versions)],
                  ["threshold", `${fmtNum(m.threshold, 4)} - ${m.threshold_rule ?? ""}`],
                  ["feature transform", m.feature_transform ?? "—"],
                  ["features", (m.features ?? []).join(", ") || "—"],
                  ["params", m.params ? JSON.stringify(m.params) : "—"],
                ]}
              />
            </div>
          </details>
        )}
      </div>
    </Card>
  );
}

function SummaryPanels({ s }: { s: AnomalySummary }) {
  const byVersion = s.by_agent_version.map((r) => ({ ...r, label: `${r.agent_id} ${r.agent_version}`, other: r.alerts - r.high_or_critical }) as Row);
  const series = [
    { key: "high_or_critical", label: "High or critical", color: SERIES[1] },
    { key: "other", label: "Low or medium", color: SERIES[0] },
  ];
  const verdicts = Object.entries(s.feedback_verdicts ?? {});
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <ChartFrame
        title="Alerts by agent version"
        subtitle="Split by severity in the selected time range"
        legend={series.map((x) => ({ label: x.label, color: x.color }))}
        table={{
          columns: [
            { key: "agent_id", header: "Agent" },
            { key: "agent_version", header: "Version" },
            { key: "alerts", header: "Alerts", align: "right", render: (r: Row) => fmtInt(r.alerts) },
            { key: "high_or_critical", header: "High/critical", align: "right", render: (r: Row) => fmtInt(r.high_or_critical) },
          ],
          rows: byVersion,
        }}
      >
        {byVersion.length ? <BarsChart data={byVersion} categoryKey="label" series={series} horizontal stacked /> : <EmptyState title="No alerts in range" />}
      </ChartFrame>
      <Card title="Alerts by detector, type and severity" subtitle={verdicts.length ? `Analyst feedback so far: ${verdicts.map(([k, v]) => `${k} ${v}`).join(" · ")}` : "No analyst feedback recorded yet"} bodyClassName="p-3">
        {s.by_detector_type_severity.length ? (
          <DataTable
            dense
            maxHeight={360}
            clientSort
            rows={s.by_detector_type_severity as unknown as Row[]}
            rowKey={(r, i) => `${r.detector}-${r.anomaly_type}-${r.severity}-${i}`}
            columns={[
              { key: "detector", header: "Detector", render: (r) => <span className="mono">{String(r.detector)}</span> },
              { key: "anomaly_type", header: "Type" },
              { key: "severity", header: "Severity", render: (r) => <SeverityBadge severity={String(r.severity)} /> },
              { key: "alerts", header: "Alerts", align: "right", render: (r) => fmtInt(r.alerts) },
              { key: "agents", header: "Agents", align: "right", render: (r) => fmtInt(r.agents) },
            ]}
          />
        ) : (
          <EmptyState title="No alerts in range" />
        )}
      </Card>
    </div>
  );
}

function AlertsBrowser({ summary }: { summary?: AnomalySummary }) {
  const { days } = useDays();
  const [sp, setSp] = useSearchParams();
  const [filters, setFilters] = useState<AnomalyFilters>({});
  const [offset, setOffset] = useState(0);
  const selected = sp.get("alert");
  const setSelected = (id: string | null) => {
    const next = new URLSearchParams(sp);
    if (id) next.set("alert", id);
    else next.delete("alert");
    setSp(next, { replace: true });
  };
  const agents = useAgents();
  const q = useAnomalies(days, filters, LIMIT, offset);
  useEffect(() => setOffset(0), [filters, days]);

  const detectors = useMemo(() => Array.from(new Set(summary?.by_detector_type_severity.map((r) => r.detector) ?? [])).sort(), [summary]);
  const types = useMemo(() => Array.from(new Set(summary?.by_detector_type_severity.map((r) => r.anomaly_type) ?? [])).sort(), [summary]);
  const agentIds = useMemo(() => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])), [agents.data]);
  const set = (k: keyof AnomalyFilters) => (v: string) => setFilters((f) => ({ ...f, [k]: v || undefined }));

  const cols: Column<AnomalyRow>[] = [
    { key: "event_time", header: "Time", render: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDateTime(r.event_time)}</span> },
    { key: "severity", header: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> },
    { key: "anomaly_type", header: "Type", render: (r) => <span className="font-medium">{r.anomaly_type}</span> },
    { key: "detector", header: "Detector", render: (r) => <span className="mono">{r.detector}</span> },
    { key: "agent", header: "Agent", render: (r) => <span className="whitespace-nowrap">{r.agent_id} <span className="mono text-ink-2">{r.agent_version}</span></span> },
    { key: "score", header: "Score", align: "right", render: (r) => fmtNum(r.score, 3) },
    { key: "explanation", header: "Explanation", className: "max-w-[420px] text-ink-2", render: (r) => <span className="line-clamp-2">{r.explanation}</span> },
    {
      key: "feedback",
      header: "Feedback",
      render: (r) => (r.feedback?.length ? <span className="flex flex-wrap gap-1">{r.feedback.map((f, i) => <Tag key={i}>{f.verdict}</Tag>)}</span> : <span className="text-muted">—</span>),
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_420px]">
      <Card title="Alerts" subtitle="Select an alert to see evidence and leave feedback" bodyClassName="p-3">
        <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
          <Field label="Severity">
            <Select value={filters.severity ?? ""} onChange={set("severity")} options={["low", "medium", "high", "critical"]} placeholder="Any" />
          </Field>
          <Field label="Type">
            <Select value={filters.anomaly_type ?? ""} onChange={set("anomaly_type")} options={types} placeholder="Any" />
          </Field>
          <Field label="Detector">
            <Select value={filters.detector ?? ""} onChange={set("detector")} options={detectors} placeholder="Any" />
          </Field>
          <Field label="Agent">
            <Select value={filters.agent_id ?? ""} onChange={set("agent_id")} options={agentIds} placeholder="Any" />
          </Field>
          <Field label="Test run id">
            <input className="input mono" placeholder="TR-…" value={filters.test_run_id ?? ""} onChange={(e) => set("test_run_id")(e.target.value.trim())} />
          </Field>
        </div>
        {q.isLoading ? (
          <SkeletonRows rows={8} />
        ) : q.isError && !q.data ? (
          <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
        ) : q.data ? (
          <>
            <div className={q.isFetching ? "opacity-60" : ""}>
              <DataTable
                columns={cols}
                rows={q.data.rows}
                rowKey={(r) => r.alert_id}
                onRowClick={(r) => setSelected(r.alert_id)}
                selectedKey={selected}
                dense
                maxHeight={560}
                caption="Anomaly alerts"
                empty={<EmptyState title="No alerts match these filters" icon="search" />}
              />
            </div>
            <Pagination offset={offset} limit={LIMIT} count={q.data.rows.length} hasMore={q.data.has_more} fetching={q.isFetching} onChange={setOffset} />
          </>
        ) : null}
      </Card>
      <AlertDetail id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function AlertDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useAnomaly(id);
  const fb = useAnomalyFeedback();
  const [note, setNote] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setNote("");
    fb.reset();
    if (id) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!id)
    return (
      <Card title="Alert detail">
        <EmptyState title="No alert selected">Pick an alert from the table to see its explanation, supporting metrics, related runs and feedback.</EmptyState>
      </Card>
    );
  const a = q.data?.alert;
  return (
    <div ref={ref} className="min-w-0">
    <Card
      title={a ? `${a.anomaly_type}` : "Alert detail"}
      subtitle={<span className="mono">{id}</span>}
      actions={
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Close
        </button>
      }
    >
      {q.isLoading ? (
        <LoadingBlock height={200} />
      ) : q.isError ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : a ? (
        <div className="flex flex-col gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={a.severity} />
            <span className="mono text-ink-2">{a.detector}</span>
            {a.detector_version && <span className="text-muted">({a.detector_version})</span>}
            <span className="num text-ink-2">score {fmtNum(a.score, 3)}</span>
          </div>
          <p className="text-sm text-ink">{a.explanation}</p>
          <KeyValues
            cols={1}
            items={[
              ["agent", `${a.agent_name ?? a.agent_id} ${a.agent_version}`],
              ["test run", a.test_run_id ?? "—"],
              ["window", a.window_start === a.window_end ? fmtDateTime(a.window_start) : `${fmtDateTime(a.window_start)} → ${fmtDateTime(a.window_end)}`],
              ...Object.entries(a.supporting_metrics ?? {}).map(([k, v]) => [k, fmtNum(v, 3)] as [string, string]),
            ]}
          />
          {a.trace_id && (
            <Link className="btn btn-sm self-start" to={`/runs/${a.trace_id}`}>
              Open trace waterfall →
            </Link>
          )}
          {q.data!.related_runs.length > 0 && (
            <div>
              <div className="label mb-1">Related runs ({q.data!.related_runs.length})</div>
              <ul className="flex max-h-40 flex-col gap-0.5 overflow-auto">
                {q.data!.related_runs.map((r) => (
                  <li key={String(r.run_id)} className="flex items-center justify-between gap-2 border-b border-line/60 py-0.5">
                    <Link className="link mono" to={`/runs/${String(r.trace_id)}`}>
                      {String(r.run_id)}
                    </Link>
                    <span className="num text-ink-2">
                      {String(r.status)} · {fmtMs(r.latency_ms)} · {fmtInt(r.total_tokens)} tok
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="rounded-md border border-line p-2">
            <div className="label mb-1">Analyst feedback</div>
            {q.data!.feedback.length ? (
              <ul className="mb-2 flex flex-col gap-1">
                {q.data!.feedback.map((f, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2">
                    <Badge tone={f.verdict === "useful" ? "good" : f.verdict === "noisy" ? "warning" : "neutral"}>{f.verdict}</Badge>
                    <span className="text-ink-2">{f.note ?? ""}</span>
                    <span className="text-muted">
                      {f.reviewer} · {fmtDateTime(f.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mb-2 text-muted">No feedback yet.</div>
            )}
            <textarea className="input h-14 py-1" maxLength={1000} placeholder="Optional note (max 1000 chars)" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="mt-2 flex flex-wrap gap-2">
              {(["useful", "noisy", "acknowledged"] as const).map((v) => (
                <button key={v} type="button" className="btn btn-sm" disabled={fb.isPending} onClick={() => fb.mutate({ id, verdict: v, note: note.trim() || undefined }, { onSuccess: () => setNote("") })}>
                  Mark {v}
                </button>
              ))}
            </div>
            {fb.isError && <div className="mt-2"><ErrorPanel error={fb.error} title="Feedback not saved" /></div>}
            {fb.isSuccess && <div className="mt-2 text-good-ink">Feedback saved ({fb.data.verdict}).</div>}
          </div>
        </div>
      ) : null}
    </Card>
    </div>
  );
}
