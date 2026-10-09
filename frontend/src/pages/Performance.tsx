import { usePerformance } from "../api/hooks";
import type { QueryResult, Row } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Note, PageHeader, QueryMeta } from "../components/ui/Card";
import { ErrorPanel, LoadingBlock, EmptyState } from "../components/ui/states";
import { ResultCard, tableColumns } from "../components/ui/ResultCard";
import { ChartFrame, ORDINAL, SERIES } from "../components/charts/ChartFrame";
import { BarsChart, TimeSeriesChart } from "../components/charts/Charts";
import { fmtCompact, fmtHour, fmtMs, fmtPctRaw } from "../lib/format";

const meta = (r: QueryResult) => <QueryMeta elapsed={r.elapsed_ms} stats={r.trino_stats} cached={r.cached} />;

export default function Performance() {
  const { days } = useDays();
  const q = usePerformance(days);
  const d = q.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Performance Analytics"
        description="Latency distributions, throughput, tool reliability, errors and token/cost usage - each panel is a named Trino query over the Iceberg lakehouse."
      />
      <Note>Latency and tokens are simulated by deterministic mock agents. Costs are estimates from a local pricing table (config/pricing.yaml), not provider prices.</Note>
      {q.isLoading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <LoadingBlock height={320} label="Running Trino queries…" />
          <LoadingBlock height={320} />
        </div>
      ) : q.isError && !d ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : d ? (
        <div className={`flex flex-col gap-4 ${q.isFetching ? "opacity-70 transition-opacity" : ""}`}>
          <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
            <LatencyChart r={d.latency_percentiles_by_version} />
            <ToolCharts r={d.tool_performance} />
          </div>
          <Throughput r={d.hourly_throughput} />
          <ResultCard result={d.error_categories} title="Run outcomes and error categories by agent version" subtitle="Status is the run outcome; task success additionally requires a correct, schema-valid answer." />
          <ResultCard result={d.token_and_cost_summary} title="Tokens and estimated cost by model and version" subtitle="est., local pricing table - runs_without_pricing counts runs with no configured price" />
          <ResultCard result={d.streaming_batch_stats} title="Spark streaming batch statistics" subtitle="Micro-batch durations and ingest lag of the streaming jobs" />
        </div>
      ) : null}
    </div>
  );
}

function versionLabel(r: Row) {
  return `${String(r.agent_name ?? r.agent_id ?? "")} ${String(r.agent_version ?? "")}`.trim();
}

function LatencyChart({ r }: { r?: QueryResult }) {
  if (!r) return <EmptyState title="Latency query returned nothing" />;
  const data = r.rows.map((x) => ({ ...x, label: versionLabel(x) }));
  const series = [
    { key: "p50_ms", label: "p50", color: ORDINAL[0] },
    { key: "p90_ms", label: "p90", color: ORDINAL[1] },
    { key: "p95_ms", label: "p95", color: ORDINAL[2] },
    { key: "p99_ms", label: "p99", color: ORDINAL[3] },
  ];
  return (
    <ChartFrame
      title="Latency percentiles by agent version"
      subtitle="p50 → p99, simulated end-to-end run latency"
      legend={series.map((s) => ({ label: s.label, color: s.color }))}
      table={{ columns: tableColumns(r), rows: r.rows }}
      meta={meta(r)}
    >
      {data.length ? <BarsChart data={data} categoryKey="label" series={series} horizontal valueFormat={fmtMs} /> : <EmptyState title="No runs in range" />}
    </ChartFrame>
  );
}

function ToolCharts({ r }: { r?: QueryResult }) {
  if (!r) return <EmptyState title="Tool query returned nothing" />;
  const sorted = [...r.rows].sort((a, b) => Number(b.non_ok_pct ?? 0) - Number(a.non_ok_pct ?? 0));
  const breakdown = [
    { key: "timeouts", label: "Timeouts", color: SERIES[0] },
    { key: "tool_errors", label: "Tool errors", color: SERIES[1] },
    { key: "invalid_args", label: "Invalid args", color: SERIES[2] },
    { key: "policy_denied", label: "Policy denied", color: SERIES[3] },
  ];
  return (
    <div className="flex flex-col gap-4">
      <ChartFrame
        title="Tool reliability: non-OK call rate"
        subtitle="Share of tool calls that did not return OK (timeouts, errors, invalid args, denials)"
        table={{ columns: tableColumns(r), rows: sorted }}
        meta={meta(r)}
      >
        {sorted.length ? (
          <BarsChart data={sorted} categoryKey="tool_name" series={[{ key: "non_ok_pct", label: "Non-OK calls" }]} horizontal valueFormat={(v) => fmtPctRaw(v, 1)} />
        ) : (
          <EmptyState title="No tool calls in range" />
        )}
      </ChartFrame>
      <ChartFrame
        title="Tool failure breakdown"
        subtitle="Count of non-OK tool calls by failure type"
        legend={breakdown.map((s) => ({ label: s.label, color: s.color }))}
        table={{ columns: tableColumns(r, ["tool_name", "calls", "retries", "timeouts", "tool_errors", "invalid_args", "policy_denied", "avg_ms", "p95_ms"]), rows: sorted }}
      >
        {sorted.length ? <BarsChart data={sorted} categoryKey="tool_name" series={breakdown} horizontal stacked valueFormat={fmtCompact} /> : <EmptyState title="No tool calls in range" />}
      </ChartFrame>
    </div>
  );
}

function Throughput({ r }: { r?: QueryResult }) {
  if (!r) return <EmptyState title="Throughput query returned nothing" />;
  const rows = [...r.rows].sort((a, b) => String(a.event_hour).localeCompare(String(b.event_hour)));
  const table = { columns: tableColumns(r, ["event_hour", "events", "runs", "spans", "avg_events_per_sec"]), rows };
  if (!rows.length) return <EmptyState title="No events in range" />;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <ChartFrame title="Events per hour" subtitle="All telemetry events landed in raw_agent_events, by event hour" table={table} meta={meta(r)}>
        <TimeSeriesChart data={rows} xKey="event_hour" series={[{ key: "events", label: "Events" }]} xFormat={fmtHour} />
      </ChartFrame>
      <ChartFrame title="Agent runs per hour" subtitle="Runs (tasks) completed per event hour" table={table}>
        <TimeSeriesChart data={rows} xKey="event_hour" series={[{ key: "runs", label: "Runs" }]} xFormat={fmtHour} />
      </ChartFrame>
    </div>
  );
}
