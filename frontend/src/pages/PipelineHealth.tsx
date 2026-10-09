import type { ReactNode } from "react";
import { useDataQuality, usePipelineHealth } from "../api/hooks";
import type { PipelineHealth as PH, Row, SparkQuery } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, KeyValues, Note, PageHeader } from "../components/ui/Card";
import { DataTable } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, LoadingBlock } from "../components/ui/states";
import { ResultCard } from "../components/ui/ResultCard";
import { Badge, StatusBadge } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { ChartFrame } from "../components/charts/ChartFrame";
import { BarsChart } from "../components/charts/Charts";
import { fmtBytes, fmtCompact, fmtDateTime, fmtInt, fmtMs, fmtNum, fmtRelative } from "../lib/format";

export default function PipelineHealth() {
  const q = usePipelineHealth(10_000);
  const d = q.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Pipeline Health"
        description="Live status of Kafka ingestion, Spark Structured Streaming, the Iceberg lakehouse (via Trino), PostgreSQL and Airflow. Auto-refreshes every 10 seconds."
        actions={
          <>
            <span className="text-xs text-muted">{d ? `Checked ${fmtRelative(d.checked_at)} · ${fmtDateTime(d.checked_at)}` : ""}</span>
            <button type="button" className="btn btn-sm" onClick={() => q.refetch()} disabled={q.isFetching}>
              <Icon name="refresh" size={14} className={q.isFetching ? "animate-spin" : ""} /> {q.isFetching ? "Checking…" : "Refresh"}
            </button>
          </>
        }
      />
      {q.isLoading ? (
        <LoadingBlock height={300} label="Checking pipeline components…" />
      ) : q.isError && !d ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} title="Pipeline health endpoint unavailable" />
      ) : d ? (
        <>
          {q.isError && <ErrorPanel error={q.error} title="Latest refresh failed - showing the previous check" />}
          <Components d={d} />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Kafka d={d} />
            <Trino d={d} />
          </div>
          <Spark d={d} />
        </>
      ) : null}
      <DataQuality />
    </div>
  );
}

function Components({ d }: { d: PH }) {
  const c = d.components;
  const facts: Record<string, ReactNode> = {
    kafka: c.kafka?.topics ? `${Object.keys(c.kafka.topics).length} topics${c.kafka.missing_topics?.length ? ` · missing: ${c.kafka.missing_topics.join(", ")}` : ""}` : null,
    spark: c.spark?.heartbeat_age_s !== undefined ? `heartbeat ${fmtNum(c.spark.heartbeat_age_s, 1)} s ago · ${Object.keys(c.spark.queries ?? {}).length} streaming queries` : null,
    trino: c.trino?.ping_ms !== undefined ? `ping ${fmtMs(c.trino.ping_ms)}` : null,
    postgres: "operational store (test runs, feedback)",
    airflow: "orchestration (optional profile)",
  };
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {Object.entries(c).map(([name, comp]) => (
        <div key={name} className="card flex flex-col gap-1.5 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-semibold capitalize text-ink">{name}</span>
            <StatusBadge status={comp?.status} />
          </div>
          {facts[name] && <div className="text-xs text-ink-2">{facts[name]}</div>}
          {comp?.error && <div className="break-words text-xs text-warning-ink">{String(comp.error)}</div>}
          {comp?.check_ms !== undefined && <div className="num text-2xs text-muted">check took {fmtMs(comp.check_ms)}</div>}
        </div>
      ))}
    </div>
  );
}

function Kafka({ d }: { d: PH }) {
  const topics = Object.entries(d.components.kafka?.topics ?? {}).map(([topic, v]) => ({ topic, ...v }) as Row);
  return (
    <ChartFrame
      title="Kafka topics"
      subtitle="Messages retained per topic (sum of partition end offsets)"
      table={{
        columns: [
          { key: "topic", header: "Topic", render: (r: Row) => <span className="mono">{String(r.topic)}</span> },
          { key: "partitions", header: "Partitions", align: "right", render: (r: Row) => fmtInt(r.partitions) },
          { key: "messages_total", header: "Messages", align: "right", render: (r: Row) => fmtInt(r.messages_total) },
        ],
        rows: topics,
      }}
    >
      {topics.length ? (
        <>
          <BarsChart data={topics} categoryKey="topic" series={[{ key: "messages_total", label: "Messages" }]} horizontal />
          {topics.some((t) => String(t.topic).includes("dlq")) && (
            <div className="px-2 text-xs text-ink-2">
              Dead-letter topic:{" "}
              {topics
                .filter((t) => String(t.topic).includes("dlq"))
                .map((t) => `${String(t.topic)} = ${fmtInt(t.messages_total)} messages`)
                .join(", ")}
            </div>
          )}
        </>
      ) : (
        <EmptyState title="No topic information" />
      )}
    </ChartFrame>
  );
}

function Trino({ d }: { d: PH }) {
  const t = d.components.trino;
  const tables = Object.entries(t?.lakehouse_tables ?? {})
    .map(([table, v]) => ({ table, ...v }) as Row)
    .sort((a, b) => Number(b.rows) - Number(a.rows));
  const rq = t?.recent_queries;
  return (
    <Card title="Trino & lakehouse tables" subtitle={rq ? `Last ${rq.window_minutes} min: ${fmtInt(rq.finished)} queries finished · avg ${fmtMs(rq.avg_ms)} · p95 ${fmtMs(rq.p95_ms)}` : "Iceberg tables in lakehouse.analytics"} bodyClassName="p-3">
      {tables.length ? (
        <DataTable
          dense
          clientSort
          maxHeight={360}
          rows={tables}
          rowKey={(r) => String(r.table)}
          columns={[
            { key: "table", header: "Table", render: (r) => <span className="mono">{String(r.table)}</span> },
            { key: "rows", header: "Rows", align: "right", render: (r) => fmtInt(r.rows) },
            { key: "bytes", header: "Size", align: "right", render: (r) => fmtBytes(r.bytes) },
            { key: "files", header: "Files", align: "right", render: (r) => fmtInt(r.files) },
          ]}
        />
      ) : (
        <EmptyState title="No lakehouse table stats" />
      )}
    </Card>
  );
}

function Spark({ d }: { d: PH }) {
  const s = d.components.spark;
  const queries = Object.entries(s?.queries ?? {});
  if (!queries.length) return <Card title="Spark streaming"><EmptyState title="No streaming query progress reported" /></Card>;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      {queries.map(([name, q]) => (
        <SparkQueryCard key={name} name={name} q={q} />
      ))}
    </div>
  );
}

function SparkQueryCard({ name, q }: { name: string; q: SparkQuery }) {
  const batches = (q.recent_batches ?? []).map((b) => ({ ...b, label: `#${b.batch_id}` }) as Row);
  return (
    <Card title={<span className="mono">{name}</span>} subtitle="Spark Structured Streaming query" actions={<StatusBadge status={q.status} />} bodyClassName="p-3">
      <div className="flex flex-col gap-3">
        <KeyValues
          items={[
            ["last batch", q.last_batch_id ?? "—"],
            ["last progress", q.last_progress_at ? `${fmtRelative(q.last_progress_at)}` : "—"],
            ["consumer lag (messages)", <span key="lag" className={Number(q.consumer_lag_messages) > 0 ? "font-semibold text-warning-ink" : ""}>{fmtInt(q.consumer_lag_messages)}</span>],
            ["last trigger duration", fmtMs(q.last_trigger_ms)],
            ["input rows/s", fmtNum(q.input_rows_per_sec, 1)],
            ["processed rows/s", fmtNum(q.processed_rows_per_sec, 1)],
            ["last batch input rows", fmtInt(q.last_input_rows)],
            ["watermark", q.watermark ? fmtDateTime(q.watermark) : "none"],
            ["rows dropped by watermark", fmtInt(q.rows_dropped_by_watermark)],
          ]}
        />
        {q.exception && (
          <div role="alert" className="rounded-md border border-critical/40 bg-critical/5 p-2 text-xs text-critical-ink">
            <Badge tone="critical">exception</Badge> <span className="mono break-words">{q.exception}</span>
          </div>
        )}
        {batches.length > 0 && (
          <ChartFrame
            title="Rows per recent micro-batch"
            subtitle="Last batches reported by the query's progress listener"
            table={{
              columns: [
                { key: "batch_id", header: "Batch", align: "right", render: (r: Row) => fmtInt(r.batch_id) },
                { key: "rows", header: "Rows", align: "right", render: (r: Row) => fmtInt(r.rows) },
                { key: "trigger_ms", header: "Trigger duration", align: "right", render: (r: Row) => fmtMs(r.trigger_ms) },
                { key: "at", header: "At", render: (r: Row) => fmtDateTime(r.at) },
              ],
              rows: batches,
            }}
          >
            <BarsChart data={batches} categoryKey="label" series={[{ key: "rows", label: "Rows" }]} height={180} valueFormat={fmtCompact} />
          </ChartFrame>
        )}
      </div>
    </Card>
  );
}

function DataQuality() {
  const { days } = useDays();
  const q = useDataQuality(days);
  return (
    <Card
      title="Data quality"
      subtitle={`Quarantine, duplicates, orphan spans, run/span consistency and timestamp checks over the last ${days} day${days > 1 ? "s" : ""}`}
      actions={
        <button type="button" className="btn btn-sm" onClick={() => q.refetch()} disabled={q.isFetching}>
          <Icon name="refresh" size={14} /> {q.isFetching ? "Running…" : "Re-run"}
        </button>
      }
      bodyClassName="p-3"
    >
      {q.isLoading ? (
        <div className="flex flex-col gap-2">
          <Note>Running six data-quality queries on Trino over the raw event table - this can take 30 seconds or more.</Note>
          <LoadingBlock height={200} />
        </div>
      ) : q.isError && !q.data ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : q.data ? (
        <div className={`flex flex-col gap-4 ${q.isFetching ? "opacity-70" : ""}`}>
          {q.data.dq_scorecard && (
            <ResultCard
              result={q.data.dq_scorecard}
              title="Data-quality scorecard"
              subtitle="One row per check. REVIEW/FAIL mark checks above their tolerance - dirty records are injected on purpose by some scenarios."
              render={{ result: (r) => <StatusBadge status={String(r.result).toLowerCase() === "pass" ? "pass" : String(r.result).toLowerCase() === "fail" ? "fail" : "review"} label={String(r.result)} /> }}
            />
          )}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {Object.entries(q.data)
              .filter(([k]) => k !== "dq_scorecard")
              .map(([k, r]) => (
                <ResultCard key={k} result={r} maxHeight={280} />
              ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
