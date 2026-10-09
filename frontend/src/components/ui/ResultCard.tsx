import type { ReactNode } from "react";
import type { QueryResult, Row } from "../../api/types";
import { Card, QueryMeta } from "./Card";
import { AutoTable } from "./DataTable";
import { EmptyState } from "./states";
import type { Column } from "./DataTable";
import { fmtCell, humanize, isNumericColumn } from "../../lib/format";

/** Card that renders one named Trino query result as a sortable table with subtle execution metadata. */
export function ResultCard({
  result,
  title,
  subtitle,
  render,
  hide,
  maxHeight = 380,
  actions,
  children,
}: {
  result: QueryResult | undefined;
  title?: ReactNode;
  subtitle?: ReactNode;
  render?: Record<string, (row: Row) => ReactNode>;
  hide?: string[];
  maxHeight?: number | "none";
  actions?: ReactNode;
  children?: ReactNode;
}) {
  if (!result) return <Card title={title ?? "Result"}><EmptyState title="This query returned nothing" /></Card>;
  return (
    <Card
      title={title ?? result.title ?? result.name}
      subtitle={subtitle}
      actions={actions}
      bodyClassName="p-3"
      footer={<QueryMeta elapsed={result.elapsed_ms} stats={result.trino_stats} cached={result.cached} rowCount={result.row_count ?? result.rows.length} truncated={result.truncated} />}
    >
      {children}
      {result.rows.length ? (
        <AutoTable result={result} maxHeight={maxHeight} render={render} hide={hide} caption={String(result.title ?? result.name)} />
      ) : (
        <EmptyState title="No rows for this time range" />
      )}
    </Card>
  );
}

/** Columns for a chart's table view, derived from a query result. */
export function tableColumns(result: Pick<QueryResult, "columns" | "rows">, only?: string[]): Column<Row>[] {
  return (only ?? result.columns).map((c) => ({
    key: c,
    header: humanize(c),
    align: isNumericColumn(result.rows, c) ? ("right" as const) : ("left" as const),
    render: (r: Row) => fmtCell(c, r[c]),
  }));
}
