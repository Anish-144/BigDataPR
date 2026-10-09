import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAgents, useGateResults, useRunGate, useScenarios, useStartTestRun, useStopTestRun, useTestRun, useTestRuns } from "../api/hooks";
import type { GateLive, GateStored, Scenario, TestRunDetail, TestRunListItem } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, Field, KeyValues, KpiTile, Note, PageHeader } from "../components/ui/Card";
import { DataTable, Select, type Column } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, LoadingBlock, SkeletonRows } from "../components/ui/states";
import { Badge, SeverityBadge, StatusBadge, Tag, VerdictBadge } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { fmtCompact, fmtDateTime, fmtInt, fmtMs, fmtNum, fmtPct, fmtRelative, fmtUsd } from "../lib/format";

const ACTIVE = new Set(["queued", "running"]);
const dflt = (v: unknown) => (v === undefined || v === null || v === "" ? "" : `default: ${String(v)}`);

export default function TestingLab() {
  const [sp, setSp] = useSearchParams();
  const selected = sp.get("run");
  const select = (id: string | null) => {
    const n = new URLSearchParams(sp);
    if (id) n.set("run", id);
    else n.delete("run");
    setSp(n, { replace: true });
  };
  // Poll quickly while a run is active, slowly otherwise (new CLI/Airflow runs still appear).
  const runs = useTestRuns(50, (q) => (q.state.data?.active.length ? 3000 : 15000));
  const active = runs.data?.active ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Testing Lab"
        description="Configure and launch a workload of deterministic mock agents (same engine as the CLI). Telemetry flows through Kafka → Spark → the lakehouse, so results appear here within seconds to a minute."
      />
      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <WorkloadForm onStarted={select} activeIds={active} />
        <RunDetail id={selected} activeIds={active} />
      </div>
      <RunList runs={runs} selected={selected} onSelect={select} />
      <RegressionGate />
    </div>
  );
}

// ---------------------------------------------------------------- workload form

interface FormState {
  scenario: string;
  name: string;
  tasks: string;
  workers: string;
  seed: string;
  time_mode: string;
  sim_days: string;
  rate_per_sec: string;
  dirty_rate: string;
  notes: string;
  overrideFaults: boolean;
  faults: Record<string, string>;
  overrideMix: boolean;
  mix: Record<string, string>;
}

function blankForm(s?: Scenario, faults: string[] = []): FormState {
  return {
    scenario: s?.id ?? "",
    name: "",
    tasks: "",
    workers: "",
    seed: "",
    time_mode: "",
    sim_days: "",
    rate_per_sec: "",
    dirty_rate: "",
    notes: "",
    overrideFaults: false,
    faults: Object.fromEntries(faults.map((f) => [f, String(s?.fault_profile?.[f] ?? 0)])),
    overrideMix: false,
    mix: Object.fromEntries((s?.workload_mix ?? []).map((m) => [`${m.agent_id}@${m.version}`, String(m.weight)])),
  };
}

function WorkloadForm({ onStarted, activeIds }: { onStarted: (id: string) => void; activeIds: string[] }) {
  const sc = useScenarios();
  const agents = useAgents();
  const start = useStartTestRun();
  const scenarios = sc.data?.scenarios ?? [];
  const faultNames = sc.data?.faults ?? [];
  const [f, setF] = useState<FormState>(() => blankForm());
  const scenario = scenarios.find((s) => s.id === f.scenario);

  useEffect(() => {
    if (!f.scenario && scenarios.length) {
      const def = scenarios.find((s) => s.id === "smoke") ?? scenarios[0];
      setF(blankForm(def, faultNames));
    }
  }, [scenarios, faultNames, f.scenario]);

  const pickScenario = (id: string) => setF(blankForm(scenarios.find((s) => s.id === id), faultNames));
  const up = (k: keyof FormState) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const mixKeys = useMemo(() => (agents.data?.agents ?? []).map((a) => `${a.agent_id}@${a.agent_version}`), [agents.data]);
  const effTimeMode = f.time_mode || scenario?.time_mode || "simulated";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const num = (v: string) => (v.trim() === "" ? undefined : Number(v));
    const body: Record<string, unknown> = { scenario: f.scenario };
    if (f.name.trim()) body.name = f.name.trim();
    if (num(f.tasks) !== undefined) body.tasks = num(f.tasks);
    if (num(f.workers) !== undefined) body.workers = num(f.workers);
    if (num(f.seed) !== undefined) body.seed = num(f.seed);
    if (f.time_mode) body.time_mode = f.time_mode;
    if (num(f.sim_days) !== undefined) body.sim_days = num(f.sim_days);
    if (num(f.rate_per_sec) !== undefined) body.rate_per_sec = num(f.rate_per_sec);
    if (num(f.dirty_rate) !== undefined) body.dirty_rate = num(f.dirty_rate);
    if (f.notes.trim()) body.notes = f.notes.trim();
    if (f.overrideFaults) body.fault_profile = Object.fromEntries(Object.entries(f.faults).map(([k, v]) => [k, Number(v) || 0]));
    if (f.overrideMix) {
      body.workload_mix = Object.entries(f.mix)
        .filter(([, w]) => Number(w) > 0)
        .map(([k, w]) => {
          const [agent_id, version] = k.split("@");
          return { agent_id, version, weight: Number(w) };
        });
    }
    start.mutate(body, { onSuccess: (r) => onStarted(r.test_run_id) });
  };

  const err = start.error as ApiError | null;
  return (
    <Card title="Configure a workload" subtitle="Blank fields use the scenario's defaults. Limits: ≤ 200,000 tasks, 1-4 workers, fault rates 0-0.5, dirty rate 0-0.2.">
      {sc.isLoading ? (
        <LoadingBlock height={300} />
      ) : sc.isError ? (
        <ErrorPanel error={sc.error} onRetry={() => sc.refetch()} title="Could not load scenarios" />
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Field label="Scenario (YAML)">
            <Select value={f.scenario} onChange={pickScenario} options={scenarios.map((s) => ({ value: s.id, label: `${s.name} · ${s.file}` }))} />
          </Field>
          {scenario && (
            <div className="rounded-md border border-line bg-surface-2 p-2 text-xs text-ink-2">
              <div className="mb-1 text-ink">{scenario.description}</div>
              <div className="num flex flex-wrap gap-x-3 gap-y-0.5">
                <span>tasks {fmtInt(scenario.tasks)}</span>
                <span>workers {scenario.workers ?? "—"}</span>
                <span>time {scenario.time_mode}</span>
                {scenario.sim_days !== undefined && <span>sim days {scenario.sim_days}</span>}
                {scenario.rate_per_sec !== undefined && <span>rate {scenario.rate_per_sec}/s</span>}
                <span>seed {scenario.seed ?? "—"}</span>
                {scenario.dirty_rate !== undefined && <span>dirty {scenario.dirty_rate}</span>}
                <span>{scenario.workload_mix?.length ?? 0} agent versions</span>
                <span>{Object.values(scenario.fault_profile ?? {}).filter((v) => v > 0).length} faults enabled</span>
                {scenario.incidents?.length ? <span>{scenario.incidents.length} incident window(s)</span> : null}
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Field label="Run name">
              <input className="input mono" value={f.name} onChange={(e) => up("name")(e.target.value)} placeholder={scenario ? `default: ${scenario.name}` : "optional"} pattern="[A-Za-z0-9_\-]{1,40}" title="Letters, digits, _ and - (max 40)" />
            </Field>
            <Field label="Tasks">
              <input className="input num" type="number" min={1} max={200000} value={f.tasks} onChange={(e) => up("tasks")(e.target.value)} placeholder={dflt(scenario?.tasks)} />
            </Field>
            <Field label="Workers (1-4)">
              <input className="input num" type="number" min={1} max={4} value={f.workers} onChange={(e) => up("workers")(e.target.value)} placeholder={dflt(scenario?.workers)} />
            </Field>
            <Field label="Seed">
              <input className="input num" type="number" min={0} value={f.seed} onChange={(e) => up("seed")(e.target.value)} placeholder={dflt(scenario?.seed)} />
            </Field>
            <Field label="Time mode">
              <Select value={f.time_mode} onChange={up("time_mode")} options={["simulated", "realtime"]} placeholder={`default (${scenario?.time_mode ?? "—"})`} />
            </Field>
            <Field label="Simulated days" hint={effTimeMode !== "simulated" ? "simulated mode only" : undefined}>
              <input className="input num" type="number" step="0.1" min={0.1} max={60} value={f.sim_days} onChange={(e) => up("sim_days")(e.target.value)} placeholder={dflt(scenario?.sim_days)} disabled={effTimeMode !== "simulated"} />
            </Field>
            <Field label="Rate (tasks/s)" hint={effTimeMode !== "realtime" ? "realtime mode only" : undefined}>
              <input className="input num" type="number" step="any" min={0} max={2000} value={f.rate_per_sec} onChange={(e) => up("rate_per_sec")(e.target.value)} placeholder={dflt(scenario?.rate_per_sec)} disabled={effTimeMode !== "realtime"} />
            </Field>
            <Field label="Dirty-record rate">
              <input className="input num" type="number" step="0.001" min={0} max={0.2} value={f.dirty_rate} onChange={(e) => up("dirty_rate")(e.target.value)} placeholder={dflt(scenario?.dirty_rate ?? 0)} />
            </Field>
          </div>
          <Field label="Notes">
            <input className="input" maxLength={200} value={f.notes} onChange={(e) => up("notes")(e.target.value)} placeholder="optional, max 200 chars" />
          </Field>

          <details className="rounded-md border border-line">
            <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs font-medium text-ink">
              Failure injection
              <span className="font-normal text-ink-2">({f.overrideFaults ? "custom profile" : "scenario default"})</span>
            </summary>
            <div className="border-t border-line p-3">
              <label className="mb-2 flex items-center gap-2 text-xs text-ink">
                <input type="checkbox" checked={f.overrideFaults} onChange={(e) => setF((x) => ({ ...x, overrideFaults: e.target.checked }))} />
                Override the fault profile (per-run probability, 0-0.5)
              </label>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                {faultNames.map((fn) => (
                  <Field key={fn} label={fn}>
                    <input
                      className="input num"
                      type="number"
                      step="0.001"
                      min={0}
                      max={0.5}
                      disabled={!f.overrideFaults}
                      value={f.faults[fn] ?? "0"}
                      onChange={(e) => setF((x) => ({ ...x, faults: { ...x.faults, [fn]: e.target.value } }))}
                    />
                  </Field>
                ))}
              </div>
            </div>
          </details>

          <details className="rounded-md border border-line">
            <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs font-medium text-ink">
              Agents / versions (workload mix)
              <span className="font-normal text-ink-2">({f.overrideMix ? "custom mix" : "scenario default"})</span>
            </summary>
            <div className="border-t border-line p-3">
              <label className="mb-2 flex items-center gap-2 text-xs text-ink">
                <input type="checkbox" checked={f.overrideMix} onChange={(e) => setF((x) => ({ ...x, overrideMix: e.target.checked }))} />
                Override the workload mix (relative weights; 0 excludes a version)
              </label>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                {mixKeys.map((k) => (
                  <Field key={k} label={k}>
                    <input
                      className="input num"
                      type="number"
                      step="any"
                      min={0}
                      disabled={!f.overrideMix}
                      value={f.mix[k] ?? "0"}
                      onChange={(e) => setF((x) => ({ ...x, mix: { ...x.mix, [k]: e.target.value } }))}
                    />
                  </Field>
                ))}
              </div>
            </div>
          </details>

          {start.isError && (
            <ErrorPanel
              error={start.error}
              title={err?.status === 409 ? "A test run is already active" : err?.status === 422 ? "The API rejected this configuration" : "Could not start the test run"}
            />
          )}
          {err?.status === 409 && activeIds.length > 0 && (
            <div className="text-xs text-ink-2">
              Active:{" "}
              {activeIds.map((id) => (
                <button key={id} type="button" className="link mono mr-2" onClick={() => onStarted(id)}>
                  {id}
                </button>
              ))}
            </div>
          )}
          {start.isSuccess && (
            <div className="flex items-center gap-2 text-xs text-good-ink">
              <Icon name="check" size={14} /> Started <span className="mono">{start.data.test_run_id}</span> ({start.data.status}).
            </div>
          )}
          <div className="flex items-center gap-2">
            <button type="submit" className="btn btn-primary" disabled={start.isPending || !f.scenario}>
              <Icon name="play" size={14} /> {start.isPending ? "Starting…" : "Run benchmark"}
            </button>
            {activeIds.length > 0 && <span className="text-xs text-warning-ink">{activeIds.length} run(s) active - the API allows a limited number at once.</span>}
          </div>
        </form>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- run detail

function runStatus(d?: TestRunDetail): string {
  return d?.operational?.status ?? d?.lakehouse?.status ?? "unknown";
}

function RunDetail({ id, activeIds }: { id: string | null; activeIds: string[] }) {
  const [poll, setPoll] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (id) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [id]);
  const q = useTestRun(id, poll);
  const stop = useStopTestRun();
  const status = runStatus(q.data);
  const isActive = (id && activeIds.includes(id)) || ACTIVE.has(status);
  useEffect(() => setPoll(true), [id]);
  useEffect(() => {
    if (q.data && !isActive) setPoll(false);
  }, [q.data, isActive]);

  if (!id)
    return (
      <div ref={ref}>
        <Card title="Run status">
          <EmptyState title="No test run selected">Start a workload or pick a test run from the list below to follow its progress.</EmptyState>
        </Card>
      </div>
    );
  const d = q.data;
  const op = d?.operational;
  const requested = Number(op?.config?.tasks ?? d?.lakehouse?.requested_tasks ?? 0);
  const progress = op?.progress_tasks ?? d?.lakehouse?.total_runs ?? d?.stats.runs_landed ?? 0;
  const pct = requested > 0 ? Math.min(1, progress / requested) : null;
  return (
    <div ref={ref} className="min-w-0">
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {op?.name ?? d?.lakehouse?.test_run_name ?? "Test run"} <span className="mono text-xs font-normal text-ink-2">{id}</span>
        </span>
      }
      subtitle={isActive ? "Polling every 3 s while the run is active" : d ? `Last updated ${fmtRelative(op?.updated_at ?? d.lakehouse?.ended_at ?? d.ingest.last_ingested ?? undefined)}` : undefined}
      actions={
        <>
          <StatusBadge status={status} />
          {isActive && (
            <button type="button" className="btn btn-sm btn-danger" disabled={stop.isPending} onClick={() => stop.mutate(id)}>
              <Icon name="stop" size={13} /> Stop
            </button>
          )}
          <button type="button" className="btn btn-sm" onClick={() => q.refetch()} disabled={q.isFetching}>
            <Icon name="refresh" size={13} />
          </button>
        </>
      }
    >
      {q.isLoading ? (
        <LoadingBlock height={260} />
      ) : q.isError && !d ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : d ? (
        <div className="flex flex-col gap-3">
          {stop.data && <Note tone={stop.data.stop_signalled ? "info" : "warn"}>{stop.data.message}</Note>}
          {stop.isError && <ErrorPanel error={stop.error} title="Stop failed" />}
          {op?.error && <ErrorPanel error={new Error(op.error)} title="The run reported an error" />}
          {pct !== null && (
            <div>
              <div className="mb-1 flex justify-between text-xs text-ink-2">
                <span>Tasks generated</span>
                <span className="num">
                  {fmtInt(progress)} / {fmtInt(requested)} ({fmtPct(pct, 0)})
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-accent/15" role="progressbar" aria-valuemin={0} aria-valuemax={requested} aria-valuenow={progress}>
                <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct * 100}%` }} />
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <KpiTile label="Runs landed" value={fmtCompact(d.stats.runs_landed)} sub={`${fmtCompact(d.ingest.events_landed)} events · ${fmtInt(d.ingest.invalid_events)} invalid`} />
            <KpiTile label="Task success" value={fmtPct(d.stats.success_rate)} sub={`${fmtInt(d.stats.failed_runs)} not completed`} />
            <KpiTile label="p95 latency" value={fmtMs(d.stats.p95_latency_ms)} sub={`p50 ${fmtMs(d.stats.p50_latency_ms)} · simulated`} />
            <KpiTile label="Est. cost" value={fmtUsd(d.stats.est_cost_usd)} sub={`${fmtCompact(d.stats.tokens)} tokens · est.`} />
          </div>
          {op?.summary && (
            <KeyValues
              items={[
                ["events emitted", fmtInt(op.summary.events_emitted)],
                ["events / s (generator)", fmtNum(op.summary.events_per_sec, 1)],
                ["tasks / s (generator)", fmtNum(op.summary.tasks_per_sec, 1)],
                ["wall time", op.summary.wall_seconds !== undefined ? `${fmtNum(op.summary.wall_seconds, 1)} s` : "—"],
              ]}
            />
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-ink-2">Security findings:</span>
            {d.security_findings.length ? d.security_findings.map((s) => <span key={s.severity} className="inline-flex items-center gap-1"><SeverityBadge severity={s.severity} /> <span className="num">{fmtInt(s.n)}</span></span>) : <span className="text-muted">none</span>}
            <span className="ml-3 text-ink-2">Anomaly alerts:</span> <span className="num font-medium">{fmtInt(d.anomaly_alerts)}</span>
            <Link to={`/runs?test_run_id=${encodeURIComponent(id)}`} className="link ml-auto">
              Explore runs →
            </Link>
          </div>
          {d.by_agent.length > 0 && (
            <DataTable
              dense
              maxHeight={260}
              rows={d.by_agent}
              rowKey={(r) => `${r.agent_id}@${r.agent_version}`}
              columns={[
                { key: "agent_id", header: "Agent" },
                { key: "agent_version", header: "Version", render: (r) => <span className="mono">{r.agent_version}</span> },
                { key: "runs", header: "Runs", align: "right", render: (r) => fmtInt(r.runs) },
                { key: "success_rate", header: "Success", align: "right", render: (r) => fmtPct(r.success_rate) },
                { key: "p95_latency_ms", header: "p95", align: "right", render: (r) => fmtMs(r.p95_latency_ms) },
              ]}
            />
          )}
          {d.regression_gates.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-ink-2">Regression gates:</span>
              {d.regression_gates.map((g) => (
                <span key={g.gate_id} className="inline-flex items-center gap-1">
                  {g.agent_id} {g.baseline_version}→{g.candidate_version} <VerdictBadge verdict={g.verdict} />
                </span>
              ))}
            </div>
          )}
          <Note>Ingestion is asynchronous: events land in the lakehouse after Spark micro-batches, so "runs landed" can trail the generator by up to a minute.</Note>
        </div>
      ) : null}
    </Card>
    </div>
  );
}

// ---------------------------------------------------------------- run list

function RunList({ runs, selected, onSelect }: { runs: ReturnType<typeof useTestRuns>; selected: string | null; onSelect: (id: string) => void }) {
  const active = new Set(runs.data?.active ?? []);
  const cols: Column<TestRunListItem>[] = [
    {
      key: "name",
      header: "Test run",
      render: (t) => (
        <span className="flex flex-col">
          <span className="font-medium">
            {t.test_run_name ?? "—"} {active.has(t.test_run_id) && <Badge tone="accent" icon="play">active</Badge>}
          </span>
          <span className="mono text-2xs text-muted">{t.test_run_id}</span>
        </span>
      ),
    },
    { key: "status", header: "Status", render: (t) => <StatusBadge status={t.api_status ?? t.status} /> },
    { key: "started_at", header: "Started", render: (t) => <span className="whitespace-nowrap text-ink-2">{fmtDateTime(t.started_at)}</span> },
    { key: "time_mode", header: "Mode", render: (t) => (t.time_mode ? <Tag>{t.time_mode}</Tag> : "—") },
    { key: "requested_tasks", header: "Requested", align: "right", render: (t) => fmtInt(t.requested_tasks) },
    { key: "total_runs", header: "Runs", align: "right", render: (t) => fmtInt(t.total_runs ?? t.progress_tasks) },
    { key: "total_events", header: "Events", align: "right", render: (t) => fmtCompact(t.total_events) },
    { key: "workers", header: "Workers", align: "right", render: (t) => fmtInt(t.workers) },
    { key: "triggered_by", header: "Trigger", render: (t) => <span className="text-ink-2">{t.triggered_by ?? "—"}</span> },
    { key: "source", header: "Source", render: (t) => <span className="text-ink-2">{t.source}</span> },
  ];
  return (
    <Card title="Test runs" subtitle="Lakehouse records merged with live API status · click to inspect" bodyClassName="p-3">
      {runs.isLoading ? (
        <SkeletonRows rows={6} />
      ) : runs.isError && !runs.data ? (
        <ErrorPanel error={runs.error} onRetry={() => runs.refetch()} />
      ) : runs.data ? (
        <DataTable
          columns={cols}
          rows={runs.data.test_runs}
          rowKey={(t) => t.test_run_id}
          onRowClick={(t) => onSelect(t.test_run_id)}
          selectedKey={selected}
          dense
          maxHeight={420}
          empty={<EmptyState title="No test runs yet">Configure a workload above and press Run benchmark.</EmptyState>}
        />
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------- regression gate

interface GateView {
  gate_id: string;
  evaluated_at: string;
  agent_id: string;
  baseline_version: string;
  candidate_version: string;
  scenario_id: string | null;
  test_run_id: string | null;
  verdict: string;
  baseline_runs: number | null;
  candidate_runs: number | null;
  p_value: number | null;
  checks: { name: string; unit: string; baseline: number | null; candidate: number | null; delta: number | null; review: number; fail: number; status: string; note: string }[];
}

const fromStored = (g: GateStored): GateView => ({
  gate_id: g.gate_id,
  evaluated_at: g.evaluated_at,
  agent_id: g.agent_id,
  baseline_version: g.baseline_version,
  candidate_version: g.candidate_version,
  scenario_id: g.scenario_id,
  test_run_id: g.test_run_id,
  verdict: g.verdict,
  baseline_runs: g.baseline_runs,
  candidate_runs: g.candidate_runs,
  p_value: g.success_p_value,
  checks: g.checks.map((c) => ({
    name: c.check_name,
    unit: c.unit,
    baseline: c.baseline_value,
    candidate: c.candidate_value,
    delta: c.delta,
    review: c.review_threshold,
    fail: c.fail_threshold,
    status: c.check_status,
    note: c.note,
  })),
});

const fromLive = (g: GateLive): GateView => ({
  gate_id: g.gate_id,
  evaluated_at: g.evaluated_at,
  agent_id: g.agent_id,
  baseline_version: g.baseline?.version,
  candidate_version: g.candidate?.version,
  scenario_id: g.scenario_id,
  test_run_id: g.test_run_id,
  verdict: g.verdict,
  baseline_runs: g.baseline?.runs ?? null,
  candidate_runs: g.candidate?.runs ?? null,
  p_value: g.success_rate_p_value,
  checks: (g.checks ?? []).map((c) => ({ ...c })),
});

function fmtCheckValue(name: string, unit: string, v: number | null) {
  if (v === null || v === undefined) return "—";
  if (unit === "percentage points") return fmtPct(v, 1);
  if (name.includes("cost")) return fmtUsd(v);
  if (name.includes("latency")) return fmtMs(v);
  return fmtNum(v, 2);
}
const unitShort = (u: string) => (u === "percentage points" ? " pp" : u === "%" ? "%" : ` ${u}`);

function GateChecks({ g }: { g: GateView }) {
  return (
    <DataTable
      dense
      maxHeight="none"
      rows={g.checks}
      rowKey={(c) => c.name}
      columns={[
        { key: "name", header: "Check", render: (c) => <span className="mono">{c.name}</span> },
        { key: "baseline", header: `Baseline ${g.baseline_version}`, align: "right", render: (c) => fmtCheckValue(c.name, c.unit, c.baseline) },
        { key: "candidate", header: `Candidate ${g.candidate_version}`, align: "right", render: (c) => fmtCheckValue(c.name, c.unit, c.candidate) },
        { key: "delta", header: "Delta (worse if +)", align: "right", render: (c) => (c.delta === null ? "—" : `${c.delta > 0 ? "+" : ""}${fmtNum(c.delta, 2)}${unitShort(c.unit)}`) },
        { key: "review", header: "Review at", align: "right", render: (c) => `${fmtNum(c.review, 2)}${unitShort(c.unit)}` },
        { key: "fail", header: "Fail at", align: "right", render: (c) => `${fmtNum(c.fail, 2)}${unitShort(c.unit)}` },
        { key: "status", header: "Result", render: (c) => <StatusBadge status={c.status} /> },
        { key: "note", header: "Note", className: "text-ink-2" },
      ]}
    />
  );
}

function GateResultView({ g }: { g: GateView }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <VerdictBadge verdict={g.verdict} large />
        <div className="text-xs text-ink-2">
          <div>
            <span className="font-medium text-ink">{g.agent_id}</span> {g.baseline_version} → {g.candidate_version}
            {g.scenario_id ? ` · scenario ${g.scenario_id}` : ""}
            {g.test_run_id ? ` · ${g.test_run_id}` : ""}
          </div>
          <div className="num">
            baseline runs {fmtInt(g.baseline_runs)} · candidate runs {fmtInt(g.candidate_runs)} · success-rate p-value {g.p_value === null ? "—" : fmtNum(g.p_value, 6)} · {fmtDateTime(g.evaluated_at)}
          </div>
        </div>
      </div>
      <GateChecks g={g} />
    </div>
  );
}

function RegressionGate() {
  const { days } = useDays();
  const agents = useAgents();
  const results = useGateResults(20);
  const runGate = useRunGate();
  const testRuns = useTestRuns(100);
  const [agentId, setAgentId] = useState("");
  const [base, setBase] = useState("");
  const [cand, setCand] = useState("");
  const [scenario, setScenario] = useState("");
  const [testRunId, setTestRunId] = useState("");
  const [gateDays, setGateDays] = useState(String(days));
  useEffect(() => setGateDays(String(days)), [days]);

  const agentIds = useMemo(() => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])), [agents.data]);
  const versions = useMemo(
    () =>
      (agents.data?.agents ?? [])
        .filter((a) => a.agent_id === agentId)
        .sort((a, b) => (a.release_seq ?? 0) - (b.release_seq ?? 0))
        .map((a) => a.agent_version),
    [agents.data, agentId],
  );
  useEffect(() => {
    if (versions.length >= 2) {
      setBase(versions[versions.length - 2]);
      setCand(versions[versions.length - 1]);
    } else {
      setBase(versions[0] ?? "");
      setCand(versions[0] ?? "");
    }
  }, [versions]);
  const names = useMemo(() => Array.from(new Set((testRuns.data?.test_runs ?? []).map((t) => t.test_run_name).filter(Boolean) as string[])), [testRuns.data]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { agent_id: agentId, baseline_version: base, candidate_version: cand, days: Number(gateDays) || days };
    if (scenario.trim()) body.scenario = scenario.trim();
    if (testRunId) body.test_run_id = testRunId;
    runGate.mutate(body);
  };

  return (
    <Card
      title="Regression gate"
      subtitle="Compare a candidate version against its baseline on success rate, p95 latency, tokens, estimated cost per success, retrieval recall and security findings, using configured thresholds."
    >
      <div className="flex flex-col gap-4">
        <Note tone="warn">
          <strong>The gate recommends; a human approves.</strong> A verdict never promotes, rolls back or blocks anything automatically - it is evidence for a release
          decision made by a person.
        </Note>
        <form onSubmit={submit} className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-7">
          <Field label="Agent">
            <Select value={agentId} onChange={setAgentId} options={agentIds} placeholder="Choose agent" />
          </Field>
          <Field label="Baseline version">
            <Select value={base} onChange={setBase} options={versions} disabled={!agentId} />
          </Field>
          <Field label="Candidate version">
            <Select value={cand} onChange={setCand} options={versions} disabled={!agentId} />
          </Field>
          <Field label="Scenario (optional)">
            <input className="input mono" list="gate-scenarios" value={scenario} onChange={(e) => setScenario(e.target.value)} placeholder="e.g. regression" />
            <datalist id="gate-scenarios">
              {names.map((n) => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </Field>
          <Field label="Test run (optional)">
            <Select value={testRunId} onChange={setTestRunId} options={(testRuns.data?.test_runs ?? []).map((t) => ({ value: t.test_run_id, label: `${t.test_run_name ?? ""} · ${t.test_run_id}` }))} placeholder="Any" />
          </Field>
          <Field label="Days">
            <input className="input num" type="number" min={1} max={3650} value={gateDays} onChange={(e) => setGateDays(e.target.value)} />
          </Field>
          <div className="flex items-end">
            <button type="submit" className="btn btn-primary w-full" disabled={!agentId || !base || !cand || runGate.isPending}>
              {runGate.isPending ? "Evaluating…" : "Run gate"}
            </button>
          </div>
        </form>
        {base && cand && base === cand && <div className="text-xs text-warning-ink">Baseline and candidate are the same version.</div>}
        {runGate.isError && <ErrorPanel error={runGate.error} title="Gate evaluation failed" />}
        {runGate.isPending && <LoadingBlock height={160} label="Evaluating cohorts on Trino…" />}
        {runGate.data && !runGate.isPending && (
          <div className="rounded-md border border-accent/40 p-3">
            <div className="label mb-2">Latest evaluation</div>
            <GateResultView g={fromLive(runGate.data)} />
          </div>
        )}
        <div>
          <div className="label mb-2">Recent gate results</div>
          {results.isLoading ? (
            <SkeletonRows rows={3} />
          ) : results.isError ? (
            <ErrorPanel error={results.error} onRetry={() => results.refetch()} />
          ) : results.data?.gates.length ? (
            <div className="flex flex-col gap-2">
              {results.data.gates.map((g) => {
                const v = fromStored(g);
                return (
                  <details key={g.gate_id} className="rounded-md border border-line">
                    <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-xs">
                      <VerdictBadge verdict={v.verdict} />
                      <span className="font-medium text-ink">{v.agent_id}</span>
                      <span className="mono text-ink-2">
                        {v.baseline_version} → {v.candidate_version}
                      </span>
                      {v.scenario_id && <Tag>{v.scenario_id}</Tag>}
                      <span className="ml-auto text-muted">{fmtDateTime(v.evaluated_at)}</span>
                    </summary>
                    <div className="border-t border-line p-3">
                      <GateResultView g={v} />
                    </div>
                  </details>
                );
              })}
            </div>
          ) : (
            <EmptyState title="No gate results yet" />
          )}
        </div>
      </div>
    </Card>
  );
}
