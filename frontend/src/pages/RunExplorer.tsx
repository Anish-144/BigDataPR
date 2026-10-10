import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAgents, useRuns, useTestRuns, type RunFilters } from "../api/hooks";
import type { RunRow } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Field, PageHeader } from "../components/ui/Card";
import { DataTable, Pagination, Select, type Column } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, SkeletonRows } from "../components/ui/states";
import { Badge, StatusBadge, SuccessBadge, Tag } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { fmtDateTime, fmtInt, fmtMs, fmtUsd } from "../lib/format";

const FILTER_KEYS = ["agent_id", "agent_version", "test_run_id", "status", "success", "has_findings", "min_latency_ms", "run_id", "sort"] as const;
const LIMIT = 50;

export default function RunExplorer() {
  const { days } = useDays();
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const applied: RunFilters = useMemo(() => {
    const f: RunFilters = {};
    for (const k of FILTER_KEYS) {
      const v = sp.get(k);
      if (v) f[k] = v;
    }
    return f;
  }, [sp]);
  const offset = Number(sp.get("offset") ?? 0) || 0;
  const [draft, setDraft] = useState<RunFilters>(applied);
  useEffect(() => setDraft(applied), [applied]);

  const agents = useAgents();
  const testRuns = useTestRuns(100);
  const q = useRuns(days, applied, LIMIT, offset);

  const agentIds = useMemo(() => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])), [agents.data]);
  const versions = useMemo(
    () => Array.from(new Set(agents.data?.agents.filter((a) => !draft.agent_id || a.agent_id === draft.agent_id).map((a) => a.agent_version) ?? [])).sort(),
    [agents.data, draft.agent_id],
  );

  const apply = (f: RunFilters, newOffset = 0) => {
    const next = new URLSearchParams();
    for (const k of FILTER_KEYS) {
      const v = f[k];
      if (v) next.set(k, v);
    }
    if (newOffset) next.set("offset", String(newOffset));
    setSp(next);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    apply(draft);
  };
  const set = (k: keyof RunFilters) => (v: string) => setDraft((d) => ({ ...d, [k]: v }));

  const cols: Column<RunRow>[] = [
    { key: "event_time", header: "Time", render: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDateTime(r.event_time)}</span> },
    { key: "run_id", header: "Run", render: (r) => <span className="mono whitespace-nowrap">{r.run_id}</span> },
    {
      key: "agent",
      header: "Agent",
      render: (r) => (
        <span className="whitespace-nowrap">
          {r.agent_name} <span className="mono text-ink-2">{r.agent_version}</span>
        </span>
      ),
    },
    { key: "workload_type", header: "Workload", render: (r) => <span className="text-ink-2">{r.workload_type}</span> },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "task_success", header: "Task", render: (r) => <SuccessBadge success={r.task_success} /> },
    { key: "error_category", header: "Error", render: (r) => (r.error_category ? <span className="text-critical-ink">{r.error_category}</span> : <span className="text-muted">—</span>) },
    { key: "latency_ms", header: "Latency", align: "right", render: (r) => fmtMs(r.latency_ms) },
    { key: "total_tokens", header: "Tokens", align: "right", render: (r) => fmtInt(r.total_tokens) },
    { key: "estimated_cost_usd", header: "Est. cost", align: "right", render: (r) => fmtUsd(r.estimated_cost_usd) },
    { key: "tool_calls", header: "Tools (err)", align: "right", render: (r) => `${fmtInt(r.tool_calls)} (${fmtInt(r.tool_errors)})` },
    { key: "retries", header: "Retries", align: "right", render: (r) => fmtInt(r.retries) },
    { key: "policy_denials", header: "Denials", align: "right", render: (r) => (r.policy_denials ? <span className="font-medium text-critical-ink">{r.policy_denials}</span> : "0") },
    {
      key: "injected_faults",
      header: "Injected faults",
      title: "Ground-truth labels from the workload simulator",
      render: (r) =>
        r.injected_faults?.length ? (
          <span className="flex flex-wrap gap-1">
            {r.injected_faults.map((f) => (
              <Tag key={f}>{f}</Tag>
            ))}
          </span>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Run Explorer"
        description="Search agent runs in the lakehouse and open any run's trace waterfall. Latency, tokens and costs are simulated by deterministic mock agents (costs are estimates)."
      />
      <div className="bg-surface rounded-2xl border border-line p-5 shadow-sm">
        <div className="flex items-center gap-2 mb-4 text-sm font-bold text-ink-2 uppercase tracking-widest">
          <Icon name="search" size={16} /> Search & Filter Runs
        </div>
        <form onSubmit={onSubmit} className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-9" aria-label="Run filters">
          <Field label="Agent">
            <Select value={draft.agent_id ?? ""} onChange={(v) => setDraft((d) => ({ ...d, agent_id: v, agent_version: "" }))} options={agentIds} placeholder="Any agent" />
          </Field>
          <Field label="Version">
            <Select value={draft.agent_version ?? ""} onChange={set("agent_version")} options={versions} placeholder="Any" />
          </Field>
          <Field label="Test run">
            <Select
              value={draft.test_run_id ?? ""}
              onChange={set("test_run_id")}
              options={(testRuns.data?.test_runs ?? []).map((t) => ({ value: t.test_run_id, label: `${t.test_run_name ?? ""} · ${t.test_run_id}` }))}
              placeholder="Any"
            />
          </Field>
          <Field label="Status">
            <Select value={draft.status ?? ""} onChange={set("status")} options={["completed", "failed", "timeout"]} placeholder="Any" />
          </Field>
          <Field label="Task success">
            <Select value={draft.success ?? ""} onChange={set("success")} options={[{ value: "true", label: "Successful" }, { value: "false", label: "Unsuccessful" }]} placeholder="Any" />
          </Field>
          <Field label="Security findings">
            <Select value={draft.has_findings ?? ""} onChange={set("has_findings")} options={[{ value: "true", label: "Has findings" }, { value: "false", label: "No findings" }]} placeholder="Any" />
          </Field>
          <Field label="Min latency (ms)">
            <input className="input" type="number" min={0} inputMode="numeric" value={draft.min_latency_ms ?? ""} onChange={(e) => set("min_latency_ms")(e.target.value)} placeholder="e.g. 5000" />
          </Field>
          <Field label="Run id">
            <input className="input mono" value={draft.run_id ?? ""} onChange={(e) => set("run_id")(e.target.value.trim())} placeholder="R-…" />
          </Field>
          <Field label="Sort">
            <Select
              value={draft.sort ?? "recent"}
              onChange={set("sort")}
              options={[
                { value: "recent", label: "Most recent" },
                { value: "slowest", label: "Slowest" },
                { value: "most_tokens", label: "Most tokens" },
              ]}
            />
          </Field>
          <div className="col-span-2 flex items-end gap-3 md:col-span-4 xl:col-span-9 pt-2">
            <button type="submit" className="btn btn-primary h-10 px-5 rounded-lg shadow-sm">
              Apply Filters
            </button>
            <button type="button" className="btn h-10 px-5 rounded-lg bg-surface hover:bg-surface-2 border border-line transition-colors shadow-sm" onClick={() => apply({})}>
              Reset
            </button>
            <span className="text-[13px] font-medium text-muted ml-auto hidden sm:block">Time range: last {days} day{days > 1 ? "s" : ""}</span>
          </div>
        </form>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink tracking-tight">Run Results</h2>
          <span className="text-sm text-ink-2">Click a row to open its trace</span>
        </div>
        {q.isLoading ? (
          <SkeletonRows rows={10} />
        ) : q.isError && !q.data ? (
          <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
        ) : q.data ? (
          <>
            <div className={q.isFetching ? "opacity-60 transition-opacity" : ""}>
              <DataTable
                columns={cols}
                rows={q.data.rows}
                rowKey={(r) => r.run_id}
                onRowClick={(r) => navigate(`/runs/${r.trace_id}`)}
                maxHeight={620}
                dense
                caption="Agent runs"
                empty={<EmptyState title="No runs match these filters" icon="search">Try widening the time range or clearing filters.</EmptyState>}
              />
            </div>
            <Pagination offset={offset} limit={LIMIT} count={q.data.rows.length} hasMore={q.data.has_more} fetching={q.isFetching} onChange={(o) => apply(applied, o)} />
          </>
        ) : null}
      </div>
      {q.isError && q.data && <Badge tone="critical">Refresh failed: {(q.error as Error).message}</Badge>}
    </div>
  );
}
