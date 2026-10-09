import { useQuality } from "../api/hooks";
import type { QueryResult, Row } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, Note, PageHeader, QueryMeta } from "../components/ui/Card";
import { ErrorPanel, LoadingBlock, EmptyState } from "../components/ui/states";
import { ResultCard, tableColumns } from "../components/ui/ResultCard";
import { Tag } from "../components/ui/Badge";
import { ChartFrame, SERIES } from "../components/charts/ChartFrame";
import { BarsChart } from "../components/charts/Charts";
import { fmtPct, fmtUsd } from "../lib/format";

const label = (r: Row) => `${String(r.agent_name ?? r.agent_id ?? "")} ${String(r.agent_version ?? "")}`.trim();
const meta = (r: QueryResult) => <QueryMeta elapsed={r.elapsed_ms} stats={r.trino_stats} cached={r.cached} />;

export default function Quality() {
  const { days } = useDays();
  const q = useQuality(days);
  const d = q.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Quality & RAG Evaluation"
        description="Task correctness, structured-output validity, tool-use correctness, retrieval quality and cost per successful task, by agent version."
      />
      <Card bodyClassName="p-4">
        <div className="flex flex-col gap-2 text-sm text-ink-2">
          <div className="flex flex-wrap items-center gap-2">
            <Tag>deterministic evaluators</Tag>
            <span>
              Every score on this page comes from <strong className="text-ink">deterministic, reference-based evaluators</strong> - exact/token-F1 match against reference
              answers, JSON-schema validation, expected-tool comparisons, Recall@K / Precision@K / MRR against ground-truth documents, and a lexical groundedness proxy.
            </span>
          </div>
          <div className="text-xs">
            No model judge is used for these aggregates, so they are reproducible. Groundedness is a lexical overlap proxy, not a semantic judgment. Any model-judged score
            would be labelled separately as probabilistic.
          </div>
        </div>
      </Card>
      {q.isLoading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <LoadingBlock height={300} label="Running Trino queries…" />
          <LoadingBlock height={300} />
        </div>
      ) : q.isError && !d ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : d ? (
        <div className={`flex flex-col gap-4 ${q.isFetching ? "opacity-70 transition-opacity" : ""}`}>
          <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
            <QualityCharts r={d.quality_metrics_by_version} />
            <RetrievalChart r={d.retrieval_quality_by_version} />
          </div>
          <ResultCard
            result={d.quality_metrics_by_version}
            title="Quality metrics by agent version"
            subtitle="Rates in [0, 1] shown as %. Tool metrics apply only to tool-using agents (blank otherwise)."
          />
          <ResultCard result={d.retrieval_quality_by_version} title="Retrieval quality by version (RAG and planner agents)" subtitle="Recall@K, Precision@K, MRR vs ground-truth documents; citation coverage; lexical groundedness" />
          <CostChart r={d.cost_per_successful_task} />
          <ResultCard result={d.cost_per_successful_task} title="Cost per successful task" subtitle="est., local pricing table" />
        </div>
      ) : null}
      <Note>Estimated costs use the local illustrative pricing table for mock models; they are not real provider prices.</Note>
    </div>
  );
}

function QualityCharts({ r }: { r?: QueryResult }) {
  if (!r) return <EmptyState title="Quality query returned nothing" />;
  const data = r.rows.map((x) => ({ ...x, label: label(x) }));
  return (
    <div className="flex flex-col gap-4">
      <ChartFrame
        title="Exact-match correctness by version"
        subtitle="Share of runs whose answer matches the reference answer"
        table={{ columns: tableColumns(r, ["agent_id", "agent_version", "runs", "exact_match", "token_f1", "schema_validity"]), rows: r.rows }}
        meta={meta(r)}
      >
        {data.length ? <BarsChart data={data} categoryKey="label" series={[{ key: "exact_match", label: "Exact match" }]} horizontal valueFormat={(v) => fmtPct(v, 0)} valueDomain={[0, 1]} /> : <EmptyState title="No evaluations in range" />}
      </ChartFrame>
      <ChartFrame
        title="Hallucination-indicator rate by version"
        subtitle="Runs flagged as confidently wrong or citing unretrieved documents (deterministic check)"
        table={{ columns: tableColumns(r, ["agent_id", "agent_version", "runs", "hallucination_flag_rate"]), rows: r.rows }}
      >
        {data.length ? <BarsChart data={data} categoryKey="label" series={[{ key: "hallucination_flag_rate", label: "Hallucination flag rate" }]} horizontal valueFormat={(v) => fmtPct(v, 1)} /> : <EmptyState title="No evaluations in range" />}
      </ChartFrame>
    </div>
  );
}

function RetrievalChart({ r }: { r?: QueryResult }) {
  if (!r) return <EmptyState title="Retrieval query returned nothing" />;
  const data = r.rows.map((x) => ({ ...x, label: label(x) }));
  const series = [
    { key: "recall_at_k", label: "Recall@K", color: SERIES[0] },
    { key: "mrr", label: "MRR", color: SERIES[1] },
    { key: "groundedness", label: "Groundedness (lexical)", color: SERIES[2] },
  ];
  return (
    <ChartFrame
      title="Retrieval quality by version"
      subtitle="Ground-truth retrieval metrics and lexical groundedness; Precision@K and citation coverage are in the table view"
      legend={series.map((s) => ({ label: s.label, color: s.color }))}
      table={{ columns: tableColumns(r), rows: r.rows }}
      meta={meta(r)}
    >
      {data.length ? <BarsChart data={data} categoryKey="label" series={series} horizontal valueFormat={(v) => fmtPct(v, 0)} valueDomain={[0, 1]} /> : <EmptyState title="No retrieval evaluations in range" />}
    </ChartFrame>
  );
}

function CostChart({ r }: { r?: QueryResult }) {
  if (!r || !r.rows.length) return null;
  const data: Row[] = r.rows.map((x): Row => ({ ...x, label: label(x) })).sort((a, b) => Number(b.estimated_cost_per_success ?? 0) - Number(a.estimated_cost_per_success ?? 0));
  return (
    <ChartFrame title="Estimated cost per successful task" subtitle="est., local pricing table · total estimated cost ÷ successful tasks" table={{ columns: tableColumns(r), rows: r.rows }} meta={meta(r)}>
      <BarsChart data={data} categoryKey="label" series={[{ key: "estimated_cost_per_success", label: "Est. cost per success" }]} horizontal valueFormat={fmtUsd} />
    </ChartFrame>
  );
}
