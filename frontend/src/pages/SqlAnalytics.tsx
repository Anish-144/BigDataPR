import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useRunShowcase, useSqlShowcase } from "../api/hooks";
import type { QueryResult, Row, SqlShowcaseQuery } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, Field, PageHeader } from "../components/ui/Card";
import { AutoTable, Select } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, LoadingBlock } from "../components/ui/states";
import { Tag } from "../components/ui/Badge";
import { Icon } from "../components/ui/Icon";
import { ChartFrame } from "../components/charts/ChartFrame";
import { BarsChart, TimeSeriesChart } from "../components/charts/Charts";
import { fmtBytes, fmtCell, fmtCompact, fmtHour, fmtInt, fmtMs, humanize, isNumericColumn } from "../lib/format";

export default function SqlAnalytics() {
  const q = useSqlShowcase();
  const [sp, setSp] = useSearchParams();
  const [search, setSearch] = useState("");
  const selectedName = sp.get("q");
  const queries = q.data?.queries ?? [];
  const selected = queries.find((x) => x.name === selectedName) ?? null;

  const groups = useMemo(() => {
    const s = search.trim().toLowerCase();
    const filtered = s
      ? queries.filter((x) => [x.name, x.title, x.concept, x.question, x.file].some((f) => (f ?? "").toLowerCase().includes(s)))
      : queries;
    const m = new Map<string, SqlShowcaseQuery[]>();
    for (const x of filtered) m.set(x.file, [...(m.get(x.file) ?? []), x]);
    return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [queries, search]);

  useEffect(() => {
    if (!selectedName && queries.length) setSp({ q: queries[0].name }, { replace: true });
  }, [selectedName, queries, setSp]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="SQL Analytics"
        description={
          <>
            A curated gallery of {q.data ? q.data.count : "…"} read-only Trino queries from the project's <span className="mono">sql/</span> folder - windows, rankings,
            cohort comparisons, data-quality checks, lakehouse metadata and EXPLAIN plans. Only parameter values can be changed; there is no free-form SQL.
          </>
        }
      />
      {q.isLoading ? (
        <LoadingBlock height={400} />
      ) : q.isError ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <Card bodyClassName="p-0" className="lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-90px)]">
            <div className="border-b border-line p-2">
              <label className="relative block">
                <span className="sr-only">Search queries</span>
                <Icon name="search" size={14} className="pointer-events-none absolute left-2 top-2 text-muted" />
                <input className="input pl-7" placeholder="Search name, concept, question…" value={search} onChange={(e) => setSearch(e.target.value)} />
              </label>
            </div>
            <nav aria-label="Query gallery" className="max-h-[60vh] overflow-y-auto p-2 lg:max-h-[calc(100vh-150px)]">
              {groups.length === 0 && <div className="p-3 text-xs text-muted">No queries match “{search}”.</div>}
              {groups.map(([file, items]) => (
                <div key={file} className="mb-3">
                  <div className="mono mb-1 px-1 text-2xs font-semibold uppercase tracking-wide text-muted">{file}</div>
                  <ul className="flex flex-col gap-0.5">
                    {items.map((x) => (
                      <li key={x.name}>
                        <button
                          type="button"
                          onClick={() => setSp({ q: x.name }, { replace: false })}
                          aria-current={x.name === selectedName ? "true" : undefined}
                          className={`w-full rounded-md px-2 py-1.5 text-left ${x.name === selectedName ? "bg-accent/10" : "hover:bg-surface-2"}`}
                        >
                          <div className="text-xs font-medium text-ink">{x.title}</div>
                          <div className="mono text-2xs text-muted">{x.name}</div>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </nav>
          </Card>
          {selected ? <QueryDetail key={selected.name} query={selected} /> : <EmptyState title="Select a query from the gallery" />}
        </div>
      )}
    </div>
  );
}

function QueryDetail({ query }: { query: SqlShowcaseQuery }) {
  const { days } = useDays();
  const run = useRunShowcase();
  const [params, setParams] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(query.params).map(([k, v]) => [k, String(v)])));
  const isExplain = /^\s*EXPLAIN/i.test(query.sql.replace(/^\s*--.*$/gm, ""));

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const body: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(params)) {
      const def = query.params[k];
      body[k] = typeof def === "number" && v.trim() !== "" && !Number.isNaN(Number(v)) ? Number(v) : v;
    }
    run.mutate({ name: query.name, params: body });
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card
        title={query.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span className="mono">{query.name}</span>
            <span className="text-muted">·</span>
            <span className="mono">{query.file}</span>
            {isExplain && <Tag>EXPLAIN plan</Tag>}
          </span>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          {query.concept && (
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="label">SQL concept</span>
              <span className="text-ink">{query.concept}</span>
            </div>
          )}
          {query.question && (
            <div>
              <div className="label">Question</div>
              <p className="text-ink">{query.question}</p>
            </div>
          )}
          {query.interpretation && (
            <div>
              <div className="label">How to read the result</div>
              <p className="text-ink-2">{query.interpretation}</p>
            </div>
          )}
          <details open className="rounded-md border border-line">
            <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-ink-2">SQL (read-only, parameters bound server-side)</summary>
            <pre className="mono max-h-[360px] overflow-auto border-t border-line bg-surface-2 p-3 leading-relaxed text-ink">{query.sql}</pre>
          </details>
          <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
            {Object.keys(query.params).length === 0 && <span className="text-xs text-muted">This query has no parameters.</span>}
            {Object.entries(query.params).map(([k, def]) => (
              <Field key={k} label={k} className="w-48" hint={`default: ${String(def)}`}>
                <div className="flex gap-1">
                  <input
                    className={`input ${typeof def === "number" ? "num" : "mono"}`}
                    type={typeof def === "number" ? "number" : "text"}
                    value={params[k] ?? ""}
                    onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
                  />
                  {k === "days" && (
                    <button type="button" className="btn btn-sm h-8 whitespace-nowrap" title="Use the global time range from the top bar" onClick={() => setParams((p) => ({ ...p, days: String(days) }))}>
                      {days}d
                    </button>
                  )}
                </div>
              </Field>
            ))}
            <button type="submit" className="btn btn-primary" disabled={run.isPending}>
              <Icon name="play" size={14} /> {run.isPending ? "Running…" : "Run query"}
            </button>
          </form>
        </div>
      </Card>
      {run.isError && <ErrorPanel error={run.error} title="Query failed" onRetry={() => submit()} />}
      {run.isPending && <LoadingBlock height={200} label="Running on Trino…" />}
      {run.data && !run.isPending && <ResultView r={run.data} />}
    </div>
  );
}

function ResultView({ r }: { r: QueryResult }) {
  const s = r.trino_stats;
  const textPlan = r.columns.length === 1 && r.rows.length > 0 && typeof r.rows[0][r.columns[0]] === "string" && /plan|explain/i.test(r.columns[0] + r.name);
  return (
    <Card
      title={`Result · ${fmtInt(r.row_count ?? r.rows.length)} row${(r.row_count ?? r.rows.length) === 1 ? "" : "s"}${r.truncated ? " (truncated)" : ""}`}
      subtitle={
        <span className="num flex flex-wrap gap-x-3">
          <span>
            Elapsed <strong className="text-ink">{fmtMs(r.elapsed_ms)}</strong>
          </span>
          {s?.processedRows !== undefined && <span>Processed rows {fmtCompact(s.processedRows)}</span>}
          {s?.processedBytes !== undefined && <span>Processed bytes {fmtBytes(s.processedBytes)}</span>}
          {s?.physicalInputBytes !== undefined && <span>Physical input {fmtBytes(s.physicalInputBytes)}</span>}
          {s?.cpuTimeMillis !== undefined && <span>CPU {fmtMs(s.cpuTimeMillis)}</span>}
          {s?.peakMemoryBytes !== undefined && <span>Peak memory {fmtBytes(s.peakMemoryBytes)}</span>}
          {s?.totalSplits !== undefined && <span>Splits {fmtInt(s.totalSplits)}</span>}
          {r.query_id && <span className="mono">{r.query_id}</span>}
        </span>
      }
      bodyClassName="p-3"
    >
      {r.rows.length === 0 ? (
        <EmptyState title="Query returned no rows" />
      ) : textPlan ? (
        <pre className="mono max-h-[600px] overflow-auto rounded-md border border-line bg-surface-2 p-3 leading-snug text-ink">
          {r.rows.map((row) => String(row[r.columns[0]])).join("\n")}
        </pre>
      ) : (
        <div className="flex flex-col gap-3">
          <AutoChart r={r} />
          <AutoTable result={r} maxHeight={480} caption={r.title ?? r.name} />
        </div>
      )}
    </Card>
  );
}

const TIME_RE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}.*)?$/;

/** A simple chart when the result has label column(s) + numeric columns. One measure at a time (no dual axes). */
function AutoChart({ r }: { r: QueryResult }) {
  const numeric = r.columns.filter((c) => isNumericColumn(r.rows, c));
  const labels = r.columns.filter((c) => !numeric.includes(c));
  const measures = numeric.filter((c) => !/(^|_)(id|rank|seq|batch_id|quartile|snapshot_id)$/.test(c));
  const [measure, setMeasure] = useState<string>(measures[0] ?? "");
  useEffect(() => setMeasure(measures[0] ?? ""), [r]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!measures.length || labels.length === 0 || labels.length > 3 || r.rows.length < 2) return null;
  const isTime = labels.length === 1 && r.rows.every((row) => typeof row[labels[0]] === "string" && TIME_RE.test(String(row[labels[0]])));
  const LIMIT = 40;
  const rows: Row[] = (isTime ? r.rows : r.rows.slice(0, LIMIT)).map((row) => ({ ...row, __label: labels.map((l) => String(row[l] ?? "—")).join(" · ") }));
  if (isTime) rows.sort((a, b) => String(a.__label).localeCompare(String(b.__label)));
  const fmt = (v: number) => fmtCell(measure, v);
  return (
    <ChartFrame
      title={`${humanize(measure)} by ${labels.map(humanize).join(" · ")}`}
      subtitle={!isTime && r.rows.length > LIMIT ? `First ${LIMIT} of ${r.rows.length} rows shown in the chart; all rows are in the table below.` : "Auto chart of one numeric column; pick another below."}
      actions={
        measures.length > 1 ? (
          <Select ariaLabel="Measure to chart" className="h-7 w-48 text-xs" value={measure} onChange={setMeasure} options={measures.map((m) => ({ value: m, label: humanize(m) }))} />
        ) : undefined
      }
    >
      {isTime ? (
        <TimeSeriesChart data={rows} xKey="__label" series={[{ key: measure, label: humanize(measure) }]} xFormat={(v) => (String(v).length > 10 ? fmtHour(String(v)) : String(v))} yFormat={fmt} />
      ) : (
        <BarsChart data={rows} categoryKey="__label" series={[{ key: measure, label: humanize(measure) }]} horizontal valueFormat={fmt} />
      )}
    </ChartFrame>
  );
}
