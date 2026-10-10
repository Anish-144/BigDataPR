import { Link } from "react-router-dom";
import { useOverview, usePipelineHealth } from "../api/hooks";
import { useDays } from "../lib/timeRange";
import { Card, PageHeader } from "../components/ui/Card";
import { ErrorPanel, EmptyState, LoadingBlock } from "../components/ui/states";
import { StatusBadge } from "../components/ui/Badge";
import { ChartFrame } from "../components/charts/ChartFrame";
import { TimeSeriesChart } from "../components/charts/Charts";
import { fmtCompact, fmtHour, fmtInt, fmtMs, fmtPct, fmtUsd, fmtDateTime } from "../lib/format";
import type { HourlyTrendPoint, Row } from "../api/types";
import { Icon, type IconName } from "../components/ui/Icon";
import { motion } from "framer-motion";

export default function Overview() {
  const { days } = useDays();
  const q = useOverview(days);
  const d = q.data;

  return (
    <div className="flex flex-col gap-8 max-w-7xl mx-auto w-full">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <PageHeader
          title="Overview"
          description={
            <>
              Headline metrics for the last {days} day{days > 1 ? "s" : ""} of agent runs, from the lakehouse via Trino. 
              Workloads are deterministic mock agents; latency and tokens are simulated.
            </>
          }
        />
        <div className="flex items-center gap-3">
          <Link to="/app/testing" className="btn btn-primary h-10 px-5 rounded-full shadow-sm">
            <Icon name="play" size={16} /> Run Benchmark
          </Link>
          <Link to="/app/assistant" className="btn h-10 px-5 rounded-full bg-surface shadow-sm hover:shadow-md">
             <Icon name="assistant" size={16} /> Follow the Evidence
          </Link>
        </div>
      </div>

      {q.isError && !d ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className={`flex flex-col gap-8 ${q.isFetching && d ? "opacity-70 transition-opacity" : "transition-opacity duration-500"}`}>
          
          {/* Top KPIs - 3x2 Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            <PremiumKpiTile 
              icon="runs" 
              label="Total Agent Runs" 
              loading={!d} 
              value={fmtCompact(d?.runs.total_runs)} 
              sub={d ? `${fmtInt(d.runs.test_runs)} tests · ${fmtCompact(d.events)} events` : undefined} 
              color="accent" 
            />
            <PremiumKpiTile 
              icon="check" 
              label="Task Success Rate" 
              loading={!d} 
              value={fmtPct(d?.runs.success_rate)} 
              sub={d ? `${fmtInt(d.runs.failed_runs)} runs failed` : undefined} 
              color="good" 
            />
            <PremiumKpiTile 
              icon="perf" 
              label="P95 Latency" 
              loading={!d} 
              value={fmtMs(d?.runs.p95_latency_ms)} 
              sub="Simulated wait times" 
              color="warning" 
            />
            <PremiumKpiTile 
              icon="chart" 
              label="Estimated Cost" 
              loading={!d} 
              value={fmtUsd(d?.runs.est_cost_usd)} 
              sub={d?.cost_note ?? "Local pricing table"} 
              color="secondary" 
            />
            <PremiumKpiTile 
              icon="anomaly" 
              label="Anomaly Alerts" 
              loading={!d} 
              value={fmtInt(d?.anomalies.alerts)} 
              sub={d ? `${fmtInt(d.anomalies.high_or_critical)} high or critical` : undefined} 
              color="serious" 
            />
            <PremiumKpiTile 
              icon="security" 
              label="Security Findings" 
              loading={!d} 
              value={fmtInt(d?.security.findings)} 
              sub={d ? `${fmtInt(d.security.critical)} critical` : undefined} 
              color="critical" 
            />
          </div>

          {!d ? (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
              <LoadingBlock height={320} />
              <LoadingBlock height={320} />
              <LoadingBlock height={320} />
            </div>
          ) : d.hourly_trend.length === 0 ? (
            <EmptyState title="No runs in this time range">Start a workload from the Testing Lab or widen the time range.</EmptyState>
          ) : (
            <TrendCharts data={d.hourly_trend} dimmed={q.isFetching} />
          )}
          
          <PipelineSummary />
        </div>
      )}
    </div>
  );
}

function PremiumKpiTile({ label, value, sub, loading, icon, color }: { label: string; value: React.ReactNode; sub?: React.ReactNode; loading?: boolean; icon: IconName; color: "accent" | "good" | "warning" | "serious" | "critical" | "secondary" }) {
  const colorMap = {
    accent: "bg-accent/10 text-accent-strong border-accent/20",
    good: "bg-good/10 text-good-ink border-good/20",
    warning: "bg-warning/10 text-warning-ink border-warning/20",
    serious: "bg-serious/10 text-serious-ink border-serious/20",
    critical: "bg-critical/10 text-critical-ink border-critical/20",
    secondary: "bg-secondary/10 text-secondary border-secondary/20",
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-start gap-4 p-5 rounded-2xl bg-surface border border-line shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group"
    >
      <div className={`p-3 rounded-xl border ${colorMap[color]} shadow-sm group-hover:scale-105 transition-transform`}>
        <Icon name={icon} size={22} strokeWidth={2.5} />
      </div>
      <div className="flex flex-col min-w-0 flex-1 gap-1">
        <span className="text-[13px] font-semibold text-ink-2 uppercase tracking-wider">{label}</span>
        {loading ? (
          <div className="skeleton h-8 w-24 mt-1" />
        ) : (
          <div className="truncate text-3xl font-extrabold text-ink tracking-tight">{value}</div>
        )}
        {sub && <div className="truncate text-xs font-medium text-muted mt-1">{sub}</div>}
      </div>
    </motion.div>
  );
}

function TrendCharts({ data, dimmed }: { data: HourlyTrendPoint[]; dimmed: boolean }) {
  const rows = data as unknown as Row[];
  const table = {
    columns: [
      { key: "hour", header: "Hour", render: (r: Row) => fmtHour(r.hour) },
      { key: "runs", header: "Runs", align: "right" as const, render: (r: Row) => fmtInt(r.runs) },
      { key: "success_rate", header: "Success rate", align: "right" as const, render: (r: Row) => fmtPct(r.success_rate) },
      { key: "p95_latency_ms", header: "p95 latency", align: "right" as const, render: (r: Row) => fmtMs(r.p95_latency_ms) },
    ],
    rows,
  };
  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
      <div className="col-span-1 xl:col-span-1 rounded-2xl overflow-hidden shadow-sm border border-line bg-surface">
        <ChartFrame title="Runs per hour" subtitle="Agent runs landed per event hour" table={table} dimmed={dimmed}>
          <TimeSeriesChart data={rows} xKey="hour" series={[{ key: "runs", label: "Runs" }]} xFormat={fmtHour} yFormat={(v) => fmtCompact(v)} />
        </ChartFrame>
      </div>
      <div className="col-span-1 xl:col-span-1 rounded-2xl overflow-hidden shadow-sm border border-line bg-surface">
        <ChartFrame title="Task success rate" subtitle="Share of runs with a valid answer" table={table} dimmed={dimmed}>
          <TimeSeriesChart data={rows} xKey="hour" series={[{ key: "success_rate", label: "Success rate" }]} xFormat={fmtHour} yFormat={(v) => fmtPct(v, 0)} />
        </ChartFrame>
      </div>
      <div className="col-span-1 xl:col-span-1 rounded-2xl overflow-hidden shadow-sm border border-line bg-surface">
        <ChartFrame title="P95 Latency" subtitle="Simulated latency over time" table={table} dimmed={dimmed}>
          <TimeSeriesChart data={rows} xKey="hour" series={[{ key: "p95_latency_ms", label: "p95 latency" }]} xFormat={fmtHour} yFormat={(v) => fmtMs(v)} />
        </ChartFrame>
      </div>
    </div>
  );
}

function PipelineSummary() {
  const q = usePipelineHealth(30_000);
  return (
    <Card
      className="!rounded-2xl shadow-sm border-line overflow-hidden"
      bodyClassName="p-6 bg-gradient-to-r from-surface to-surface-2"
      title={<span className="text-lg font-bold">Pipeline Status</span>}
      subtitle="Kafka → Spark Streaming → Iceberg Lakehouse → Trino"
      actions={
        <Link to="/app/pipeline" className="btn btn-sm bg-surface shadow-sm rounded-full px-4 border border-line-strong hover:bg-surface-2">
          View Details
        </Link>
      }
    >
      {q.isLoading ? (
        <LoadingBlock height={60} />
      ) : q.isError && !q.data ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} title="Pipeline health unavailable" />
      ) : q.data ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-3">
            {Object.entries(q.data.components).map(([name, c]) => (
              <div key={name} className="flex items-center gap-2.5 rounded-lg border border-line/60 bg-surface px-4 py-2.5 shadow-sm">
                <span className="text-sm font-semibold capitalize text-ink">{name}</span>
                <StatusBadge status={c?.status} />
              </div>
            ))}
          </div>
          <div className="text-xs font-medium text-muted flex items-center gap-2">
            <Icon name="refresh" size={12} className={q.isFetching ? 'animate-spin' : ''} />
            Checked {fmtDateTime(q.data.checked_at)} · Overall health: <span className="text-ink font-bold uppercase tracking-wide">{q.data.status}</span>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
