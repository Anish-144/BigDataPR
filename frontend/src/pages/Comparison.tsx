import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useAgents, useComparison, useRegressions, useTestRuns } from "../api/hooks";
import type { ComparisonRow, Row } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, Field, Note, PageHeader } from "../components/ui/Card";
import { DataTable, type Column } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, LoadingBlock } from "../components/ui/states";
import { ResultCard } from "../components/ui/ResultCard";
import { Tag } from "../components/ui/Badge";
import { ChartFrame } from "../components/charts/ChartFrame";
import { BarsChart } from "../components/charts/Charts";
import { fmtCompact, fmtInt, fmtMs, fmtNum, fmtPct, fmtUsd, isNum } from "../lib/format";

type Dir = "higher" | "lower" | null;
interface Metric {
  key: keyof ComparisonRow;
  label: string;
  fmt: (v: unknown) => string;
  dir: Dir;
  chart?: boolean;
  note?: string;
}
const METRICS: Metric[] = [
  { key: "runs", label: "Runs", fmt: fmtInt, dir: null },
  { key: "success_rate", label: "Task success rate", fmt: (v) => fmtPct(v, 1), dir: "higher", chart: true },
  { key: "p50_latency_ms", label: "p50 latency (simulated)", fmt: fmtMs, dir: "lower" },
  { key: "p95_latency_ms", label: "p95 latency (simulated)", fmt: fmtMs, dir: "lower", chart: true },
  { key: "avg_tokens", label: "Avg tokens per run", fmt: (v) => fmtNum(v, 0), dir: "lower", chart: true },
  { key: "est_cost_usd", label: "Est. total cost", fmt: fmtUsd, dir: null, note: "est." },
  { key: "est_cost_per_success", label: "Est. cost per successful task", fmt: fmtUsd, dir: "lower", chart: true, note: "est." },
  { key: "avg_retries", label: "Avg retries per run", fmt: (v) => fmtNum(v, 3), dir: "lower" },
  { key: "exact_match", label: "Exact match", fmt: (v) => fmtPct(v, 1), dir: "higher" },
  { key: "schema_validity", label: "Schema validity", fmt: (v) => fmtPct(v, 1), dir: "higher" },
  { key: "recall_at_k", label: "Retrieval Recall@K", fmt: (v) => fmtPct(v, 1), dir: "higher", chart: true },
  { key: "hallucination_flag_rate", label: "Hallucination flag rate", fmt: (v) => fmtPct(v, 2), dir: "lower" },
  { key: "security_findings", label: "Security findings", fmt: fmtInt, dir: "lower" },
  { key: "critical_findings", label: "Critical findings", fmt: fmtInt, dir: "lower" },
  { key: "findings_per_1k_runs", label: "Findings per 1k runs", fmt: (v) => fmtNum(v, 1), dir: "lower", chart: true },
  { key: "anomaly_alerts", label: "Anomaly alerts", fmt: fmtInt, dir: "lower", chart: true },
];

export default function Comparison() {
  const { days } = useDays();
  const agents = useAgents();
  const [sp, setSp] = useSearchParams();
  const keys = useMemo(() => (agents.data?.agents ?? []).map((a) => ({ key: `${a.agent_id}@${a.agent_version}`, label: `${a.agent_name} ${a.agent_version}`, model: a.model_name })), [agents.data]);
  const selected = useMemo(() => (sp.get("v") ?? "").split(",").filter(Boolean), [sp]);
  const setSelected = (v: string[]) => {
    const n = new URLSearchParams(sp);
    if (v.length) n.set("v", v.join(","));
    else n.delete("v");
    setSp(n, { replace: true });
  };
  const toggle = (k: string) => {
    if (selected.includes(k)) setSelected(selected.filter((x) => x !== k));
    else if (selected.length < 6) setSelected([...selected, k]);
  };
  const cmp = useComparison(days, selected);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Agent Comparison"
        description="Compare 2-6 agent versions side by side on quality, latency, tokens, estimated cost, anomalies and security outcomes, then review regression cohorts."
      />
      <Card title="Versions to compare" subtitle={`${selected.length} of 6 selected · choose at least 2`}>
        {agents.isLoading ? (
          <LoadingBlock height={40} />
        ) : agents.isError ? (
          <ErrorPanel error={agents.error} onRetry={() => agents.refetch()} />
        ) : (
          <div className="flex flex-wrap gap-2">
            {keys.map((k) => {
              const on = selected.includes(k.key);
              return (
                <button
                  key={k.key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(k.key)}
                  disabled={!on && selected.length >= 6}
                  className={`rounded-md border px-2.5 py-1 text-xs ${on ? "border-accent bg-accent/10 font-medium text-accent-ink" : "border-line-strong text-ink-2 hover:bg-surface-2"} disabled:opacity-40`}
                >
                  {on ? "✓ " : ""}
                  {k.label} <span className="text-muted">· {k.model}</span>
                </button>
              );
            })}
            {selected.length > 0 && (
              <button type="button" className="btn btn-sm" onClick={() => setSelected([])}>
                Clear
              </button>
            )}
          </div>
        )}
      </Card>
      {selected.length < 2 ? (
        <EmptyState title="Select at least two versions">Pick agent versions above (e.g. a baseline and its candidate) to compare them.</EmptyState>
      ) : cmp.isLoading ? (
        <LoadingBlock height={300} />
      ) : cmp.isError && !cmp.data ? (
        <ErrorPanel error={cmp.error} onRetry={() => cmp.refetch()} />
      ) : cmp.data ? (
        cmp.data.rows.length === 0 ? (
          <EmptyState title="No runs for these versions in the selected time range" />
        ) : (
          <div className={`flex flex-col gap-4 ${cmp.isFetching ? "opacity-70" : ""}`}>
            <SideBySide rows={cmp.data.rows} />
            <Note>{cmp.data.cost_note ? `Cost: ${cmp.data.cost_note.replace(/\.?$/, ".")}` : "Estimated costs come from a local illustrative pricing table."} Latency and tokens are simulated by mock agents. A blank bar or "—" means the metric does not apply to that version (e.g. Recall@K for non-retrieval agents).</Note>
            <SmallMultiples rows={cmp.data.rows} />
          </div>
        )
      ) : null}
      <Regressions />
    </div>
  );
}

function best(rows: ComparisonRow[], m: Metric): number | null {
  if (!m.dir) return null;
  const vals = rows.map((r) => r[m.key]).filter(isNum) as number[];
  if (vals.length < 2) return null;
  const b = m.dir === "higher" ? Math.max(...vals) : Math.min(...vals);
  return vals.filter((v) => v === b).length === vals.length ? null : b;
}

function SideBySide({ rows }: { rows: ComparisonRow[] }) {
  const cols: Column<Metric>[] = [
    {
      key: "metric",
      header: "Metric",
      render: (m) => (
        <span className="flex items-center gap-1.5 whitespace-nowrap font-medium">
          {m.label}
          {m.note && <Tag>{m.note}</Tag>}
          {m.dir && <span className="text-2xs font-normal text-muted">({m.dir} is better)</span>}
        </span>
      ),
    },
    ...rows.map(
      (r): Column<Metric> => ({
        key: `${r.agent_id}@${r.agent_version}`,
        header: (
          <span className="flex flex-col">
            <span className="text-ink">{r.agent_name} {r.agent_version}</span>
            <span className="text-2xs font-normal text-muted">
              {r.model_name} · {r.prompt_version}
            </span>
          </span>
        ),
        align: "right",
        render: (m) => {
          const v = r[m.key];
          const b = best(rows, m);
          const isBest = b !== null && v === b;
          return (
            <span className={isBest ? "font-semibold text-ink" : "text-ink-2"}>
              {m.fmt(v)}
              {isBest && <span className="ml-1 text-2xs font-medium text-good-ink">★ best</span>}
            </span>
          );
        },
      }),
    ),
  ];
  return (
    <Card title="Side-by-side" subtitle="★ marks the best value in rows where a direction is meaningful" bodyClassName="p-3">
      <DataTable columns={cols} rows={METRICS} rowKey={(m) => String(m.key)} dense maxHeight="none" caption="Version comparison" />
    </Card>
  );
}

function SmallMultiples({ rows }: { rows: ComparisonRow[] }) {
  const data = rows.map((r) => ({ ...r, label: `${r.agent_name} ${r.agent_version}` }) as unknown as Row);
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-4">
      {METRICS.filter((m) => m.chart).map((m) => {
        const has = data.some((d) => isNum(d[m.key]));
        return (
          <ChartFrame
            key={String(m.key)}
            title={m.label}
            subtitle={m.dir ? `${m.dir} is better${m.note ? " · " + m.note : ""}` : undefined}
            table={{
              columns: [
                { key: "label", header: "Version" },
                { key: String(m.key), header: m.label, align: "right", render: (r: Row) => m.fmt(r[m.key]) },
              ],
              rows: data,
            }}
          >
            {has ? (
              <BarsChart data={data} categoryKey="label" series={[{ key: String(m.key), label: m.label }]} horizontal valueFormat={(v) => (m.fmt(v) === "—" ? fmtCompact(v) : m.fmt(v))} />
            ) : (
              <EmptyState title="Not applicable to these versions" />
            )}
          </ChartFrame>
        );
      })}
    </div>
  );
}

function Delta({ v, goodWhen, unit }: { v: unknown; goodWhen: "up" | "down"; unit: string }): ReactNode {
  if (!isNum(v)) return <span className="text-muted">—</span>;
  if (v === 0) return <span className="text-ink-2">0{unit}</span>;
  const good = goodWhen === "up" ? v > 0 : v < 0;
  return (
    <span className={`whitespace-nowrap font-medium ${good ? "text-good-ink" : "text-critical-ink"}`} title={good ? "improvement" : "regression"}>
      {v > 0 ? "▲ +" : "▼ "}
      {fmtNum(v, 2)}
      {unit}
    </span>
  );
}

function Regressions() {
  const { days } = useDays();
  const [scenario, setScenario] = useState("regression");
  const [applied, setApplied] = useState("regression");
  const q = useRegressions(days, applied);
  const tr = useTestRuns(100);
  const names = useMemo(() => Array.from(new Set((tr.data?.test_runs ?? []).map((t) => t.test_run_name).filter(Boolean) as string[])), [tr.data]);
  return (
    <Card
      title="Regression analysis"
      subtitle="Baseline vs candidate cohorts within a scenario, plus version-over-version change via LAG() by release sequence"
      actions={
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(scenario.trim() || "regression");
          }}
        >
          <Field label="Scenario (test run name)">
            <input className="input mono w-48" list="scenario-names" value={scenario} onChange={(e) => setScenario(e.target.value)} />
            <datalist id="scenario-names">
              {names.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </Field>
          <button type="submit" className="btn">
            Apply
          </button>
        </form>
      }
      bodyClassName="p-3"
    >
      {q.isLoading ? (
        <LoadingBlock height={240} />
      ) : q.isError && !q.data ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : q.data ? (
        <div className={`flex flex-col gap-4 ${q.isFetching ? "opacity-70" : ""}`}>
          <ResultCard
            result={q.data.cohort_ab_comparison}
            title={`Cohort A/B comparison · scenario “${applied}”`}
            subtitle="▲/▼ with green/red text = improvement/regression for the candidate. Costs are estimates."
            render={{
              delta_success_pp: (r) => <Delta v={r.delta_success_pp} goodWhen="up" unit=" pp" />,
              delta_p95_pct: (r) => <Delta v={r.delta_p95_pct} goodWhen="down" unit="%" />,
              delta_tokens_pct: (r) => <Delta v={r.delta_tokens_pct} goodWhen="down" unit="%" />,
              delta_cost_per_success_pct: (r) => <Delta v={r.delta_cost_per_success_pct} goodWhen="down" unit="%" />,
            }}
          />
          <ResultCard
            result={q.data.version_regression_lag}
            title="Version-over-version latency change"
            render={{ latency_change_pct: (r) => <Delta v={r.latency_change_pct} goodWhen="down" unit="%" /> }}
          />
          {q.data.prompt_model_comparison && <ResultCard result={q.data.prompt_model_comparison} title="Prompt version × model comparison" />}
        </div>
      ) : null}
    </Card>
  );
}
