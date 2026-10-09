import { Link } from "react-router-dom";
import { useOverview, usePipelineHealth } from "../api/hooks";
import { useDays } from "../lib/timeRange";
import { Card, KpiTile, Note, PageHeader } from "../components/ui/Card";
import { ErrorPanel, EmptyState, LoadingBlock } from "../components/ui/states";
import { StatusBadge, Tag } from "../components/ui/Badge";
import { ChartFrame } from "../components/charts/ChartFrame";
import { TimeSeriesChart } from "../components/charts/Charts";
import { fmtCompact, fmtHour, fmtInt, fmtMs, fmtPct, fmtUsd, fmtDateTime } from "../lib/format";
import type { HourlyTrendPoint, Row } from "../api/types";

export default function Overview() {
  const { days } = useDays();
  const q = useOverview(days);
  const d = q.data;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Overview"
        description={
          <>
            Headline metrics for the last {days} day{days > 1 ? "s" : ""} of agent runs, from the lakehouse via Trino. Workloads are deterministic mock agents, so
            latency and token counts are simulated.
          </>
        }
      />
      {q.isError && !d ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <>
          <div className={`grid grid-cols-2 gap-3 md:grid-cols-4 ${q.isFetching && d ? "opacity-70" : ""}`}>
            <KpiTile label="Total agent runs" loading={!d} value={fmtCompact(d?.runs.total_runs)} sub={d ? `${fmtInt(d.runs.test_runs)} test runs · ${fmtCompact(d.events)} events` : undefined} />
            <KpiTile label="Task success rate" loading={!d} value={fmtPct(d?.runs.success_rate)} sub={d ? `${fmtInt(d.runs.failed_runs)} runs not completed` : undefined} />
            <KpiTile label="p95 latency" loading={!d} value={fmtMs(d?.runs.p95_latency_ms)} tag={<Tag title="Latency comes from simulated mock agents">simulated</Tag>} />
            <KpiTile label="Tokens used" loading={!d} value={fmtCompact(d?.runs.total_tokens)} tag={<Tag title="Token counts are produced by mock agents">simulated</Tag>} />
            <KpiTile
              label="Estimated cost"
              loading={!d}
              value={fmtUsd(d?.runs.est_cost_usd)}
              tag={<Tag title={d?.cost_note ?? "Local pricing table"}>est.</Tag>}
              sub="est., local pricing table"
            />
            <KpiTile label="Anomaly alerts" loading={!d} value={fmtInt(d?.anomalies.alerts)} sub={d ? `${fmtInt(d.anomalies.high_or_critical)} high or critical` : undefined} />
            <KpiTile label="Security findings" loading={!d} value={fmtInt(d?.security.findings)} sub={d ? `${fmtInt(d.security.critical)} critical` : undefined} />
            <KpiTile label="Quarantined records" loading={!d} value={fmtInt(d?.quarantined_records)} sub="invalid events in dead-letter table" />
          </div>
          <Note>
            {d?.cost_note ? `Cost: ${d.cost_note.replace(/\.?$/, ".")}` : "Costs are estimates from a local pricing table."} Anomaly alerts and security findings are signals for review, not proof of an attack.
          </Note>
          {!d ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
              <LoadingBlock height={260} />
              <LoadingBlock height={260} />
              <LoadingBlock height={260} />
            </div>
          ) : d.hourly_trend.length === 0 ? (
            <EmptyState title="No runs in this time range">Start a workload from the Testing Lab or widen the time range.</EmptyState>
          ) : (
            <TrendCharts data={d.hourly_trend} dimmed={q.isFetching} />
          )}
        </>
      )}
      <PipelineSummary />
    </div>
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
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
      <ChartFrame title="Runs per hour" subtitle="Agent runs landed per event hour" table={table} dimmed={dimmed}>
        <TimeSeriesChart data={rows} xKey="hour" series={[{ key: "runs", label: "Runs" }]} xFormat={fmtHour} yFormat={(v) => fmtCompact(v)} />
      </ChartFrame>
      <ChartFrame title="Task success rate" subtitle="Share of runs with a correct, schema-valid answer" table={table} dimmed={dimmed}>
        <TimeSeriesChart data={rows} xKey="hour" series={[{ key: "success_rate", label: "Success rate" }]} xFormat={fmtHour} yFormat={(v) => fmtPct(v, 0)} />
      </ChartFrame>
      <ChartFrame title="p95 latency" subtitle="Per hour, simulated latency" table={table} dimmed={dimmed}>
        <TimeSeriesChart data={rows} xKey="hour" series={[{ key: "p95_latency_ms", label: "p95 latency" }]} xFormat={fmtHour} yFormat={(v) => fmtMs(v)} />
      </ChartFrame>
    </div>
  );
}

function PipelineSummary() {
  const q = usePipelineHealth(30_000);
  return (
    <Card
      title="Pipeline status"
      subtitle="Kafka → Spark Structured Streaming → Iceberg lakehouse → Trino"
      actions={
        <Link to="/pipeline" className="link text-xs">
          Open pipeline health →
        </Link>
      }
    >
      {q.isLoading ? (
        <LoadingBlock height={60} />
      ) : q.isError && !q.data ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} title="Pipeline health unavailable" />
      ) : q.data ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            {Object.entries(q.data.components).map(([name, c]) => (
              <div key={name} className="flex items-center gap-2 rounded-md border border-line px-3 py-2">
                <span className="text-sm font-medium capitalize text-ink">{name}</span>
                <StatusBadge status={c?.status} />
              </div>
            ))}
          </div>
          <div className="text-2xs text-muted">Checked {fmtDateTime(q.data.checked_at)} · overall status: {q.data.status}</div>
        </div>
      ) : null}
    </Card>
  );
}
