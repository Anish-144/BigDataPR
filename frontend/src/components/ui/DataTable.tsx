import { useMemo, useState, type ReactNode } from "react";
import type { QueryResult, Row } from "../../api/types";
import { fmtCell, humanize, isNumericColumn } from "../../lib/format";
import { EmptyState } from "./states";
import { Icon } from "./Icon";

export interface Column<R> {
  key: string;
  header: ReactNode;
  render?: (row: R) => ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  /** value used for client-side sorting (defaults to row[key]) */
  sortValue?: (row: R) => number | string | null | undefined;
  sortable?: boolean;
  title?: string;
}

export function DataTable<R>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  maxHeight = 520,
  empty,
  dense = false,
  caption,
  clientSort = false,
  nowrap = false,
}: {
  columns: Column<R>[];
  rows: R[];
  rowKey: (row: R, i: number) => string;
  onRowClick?: (row: R) => void;
  selectedKey?: string | null;
  maxHeight?: number | "none";
  empty?: ReactNode;
  dense?: boolean;
  caption?: string;
  clientSort?: boolean;
  /** keep cells on one line (dense analytical tables scroll horizontally instead of wrapping) */
  nowrap?: boolean;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const get = col.sortValue ?? ((r: R) => (r as Row)[col.key] as number | string | null | undefined);
    return [...rows].sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (va < vb ? -1 : 1) * sort.dir;
    });
  }, [rows, sort, columns]);

  if (!rows.length) return <>{empty ?? <EmptyState title="No rows" />}</>;
  const pad = dense ? "px-2 py-1" : "px-3 py-1.5";
  return (
    <div className="overflow-auto rounded-xl border border-line bg-surface shadow-sm" style={{ maxHeight: maxHeight === "none" ? undefined : maxHeight }}>
      <table className="w-full border-collapse text-left text-[13px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="sticky top-0 z-[1] bg-surface/90 backdrop-blur-md">
          <tr>
            {columns.map((c) => {
              const canSort = clientSort && c.sortable !== false;
              const active = sort?.key === c.key;
              return (
                <th
                  key={c.key}
                  scope="col"
                  title={c.title}
                  aria-sort={active ? (sort!.dir === 1 ? "ascending" : "descending") : undefined}
                  className={`whitespace-nowrap border-b border-line font-semibold text-ink-2 tracking-wide uppercase text-[11px] ${pad} ${c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : ""}`}
                >
                  {canSort ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 hover:text-ink"
                      onClick={() => setSort(active ? (sort!.dir === -1 ? { key: c.key, dir: 1 } : null) : { key: c.key, dir: -1 })}
                    >
                      {c.header}
                      <span className="text-muted">{active ? (sort!.dir === -1 ? "↓" : "↑") : ""}</span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const k = rowKey(r, i);
            const selected = selectedKey !== undefined && selectedKey === k;
            return (
              <tr
                key={k}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(r);
                        }
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
                aria-selected={onRowClick ? selected : undefined}
                className={`border-b border-line/50 last:border-b-0 transition-colors ${onRowClick ? "cursor-pointer hover:bg-surface-2/60 focus:bg-surface-2 focus:outline-none" : ""} ${selected ? "bg-accent/5 hover:bg-accent/10" : ""}`}
              >
                {columns.map((c) => (
                  <td key={c.key} className={`${pad} align-top text-ink ${nowrap ? "whitespace-nowrap" : ""} ${c.align === "right" ? "num text-right" : c.align === "center" ? "text-center" : ""} ${c.className ?? ""}`}>
                    {c.render ? c.render(r) : fmtCell(c.key, (r as Row)[c.key])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Table for a generic {columns, rows} query result: numbers right-aligned, formatted by column name. */
export function AutoTable({
  result,
  maxHeight = 420,
  render,
  hide = [],
  caption,
}: {
  result: Pick<QueryResult, "columns" | "rows">;
  maxHeight?: number | "none";
  render?: Record<string, (row: Row) => ReactNode>;
  hide?: string[];
  caption?: string;
}) {
  const cols: Column<Row>[] = result.columns
    .filter((c) => !hide.includes(c))
    .map((c) => ({
      key: c,
      header: humanize(c),
      align: isNumericColumn(result.rows, c) ? "right" : "left",
      render: render?.[c],
    }));
  return <DataTable columns={cols} rows={result.rows} rowKey={(_r, i) => String(i)} maxHeight={maxHeight} dense clientSort caption={caption} nowrap />;
}

export function Pagination({
  offset,
  limit,
  count,
  hasMore,
  onChange,
  fetching,
}: {
  offset: number;
  limit: number;
  count: number;
  hasMore: boolean;
  onChange: (offset: number) => void;
  fetching?: boolean;
}) {
  const from = count ? offset + 1 : 0;
  const to = offset + count;
  return (
    <div className="flex items-center justify-between gap-2 pt-2 text-xs text-ink-2">
      <span className="num">
        {count ? `Rows ${from.toLocaleString()}–${to.toLocaleString()}` : "No rows"}
        {fetching ? " · loading…" : ""}
      </span>
      <div className="flex items-center gap-1">
        <button type="button" className="btn btn-sm" disabled={offset === 0 || fetching} onClick={() => onChange(Math.max(0, offset - limit))}>
          <Icon name="chevronLeft" size={14} /> Prev
        </button>
        <button type="button" className="btn btn-sm" disabled={!hasMore || fetching} onClick={() => onChange(offset + limit)}>
          Next <Icon name="chevronRight" size={14} />
        </button>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium ${value === t.id ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Select({
  value,
  onChange,
  options,
  placeholder,
  className = "",
  ariaLabel,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: (string | { value: string; label: string })[];
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return (
    <select aria-label={ariaLabel} className={`input pr-6 ${className}`} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const l = typeof o === "string" ? o : o.label;
        return (
          <option key={v} value={v}>
            {l}
          </option>
        );
      })}
    </select>
  );
}
