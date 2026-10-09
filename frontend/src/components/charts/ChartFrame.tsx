import { useState, type ReactNode } from "react";
import { Icon } from "../ui/Icon";
import { DataTable, type Column } from "../ui/DataTable";
import type { Row } from "../../api/types";

/** Categorical slots, light/dark resolved by CSS variables (validated reference palette). */
export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)"];
/** Ordinal blue ramp (validated with --ordinal in both modes): low -> high. */
export const ORDINAL = ["var(--ord-1)", "var(--ord-2)", "var(--ord-3)", "var(--ord-4)"];

export const AXIS = {
  tick: { fill: "var(--chart-tick)", fontSize: 11 },
  axisLine: { stroke: "var(--chart-axis)" },
  tickLine: false as const,
};
export const GRID = { stroke: "var(--chart-grid)", strokeDasharray: undefined };

export interface LegendItem {
  label: string;
  color: string;
  kind?: "rect" | "line";
}

export function Legend({ items }: { items: LegendItem[] }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2" aria-label="Legend">
      {items.map((it) => (
        <li key={it.label} className="inline-flex items-center gap-1.5">
          {it.kind === "line" ? (
            <svg width="16" height="8" aria-hidden="true">
              <line x1="1" y1="4" x2="15" y2="4" stroke={it.color} strokeWidth="2" strokeLinecap="round" />
            </svg>
          ) : (
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: it.color }} />
          )}
          {it.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Chart container: title/subtitle, legend, optional meta line, and a table-view twin
 * (the accessible equivalent of every chart; also the relief channel for sub-3:1 hues).
 */
export function ChartFrame({
  title,
  subtitle,
  legend,
  table,
  meta,
  children,
  actions,
  dimmed,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  legend?: LegendItem[];
  table?: { columns: Column<Row>[]; rows: Row[] };
  meta?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  dimmed?: boolean;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <figure className="card m-0 flex min-w-0 flex-col">
      <figcaption className="flex items-start justify-between gap-2 px-4 pt-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-ink">{title}</div>
          {subtitle && <div className="mt-0.5 text-xs text-ink-2">{subtitle}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {table && (
            <button
              type="button"
              className="btn btn-sm"
              aria-pressed={view === "table"}
              onClick={() => setView(view === "chart" ? "table" : "chart")}
              title={view === "chart" ? "Show as table" : "Show as chart"}
            >
              <Icon name={view === "chart" ? "table" : "chart"} size={14} />
              {view === "chart" ? "Table" : "Chart"}
            </button>
          )}
        </div>
      </figcaption>
      {legend && legend.length > 1 && view === "chart" && (
        <div className="px-4 pt-2">
          <Legend items={legend} />
        </div>
      )}
      <div className={`min-w-0 px-2 pb-2 pt-2 transition-opacity ${dimmed ? "opacity-60" : ""}`}>
        {view === "chart" || !table ? (
          children
        ) : (
          <div className="px-2">
            <DataTable columns={table.columns} rows={table.rows} rowKey={(_r, i) => String(i)} dense maxHeight={320} />
          </div>
        )}
      </div>
      {meta && <div className="px-4 pb-3">{meta}</div>}
    </figure>
  );
}

/** Tooltip body: values lead (strong), series names follow; short line keys, not boxes. */
export function TooltipBody({
  label,
  rows,
}: {
  label: ReactNode;
  rows: { name: string; value: string; color: string; kind?: "line" | "rect" }[];
}) {
  return (
    <div className="pointer-events-none min-w-[140px] rounded-md border border-line bg-surface px-2.5 py-2 text-xs shadow-lg">
      <div className="mb-1 text-2xs text-muted">{label}</div>
      <ul className="flex flex-col gap-0.5">
        {rows.map((r) => (
          <li key={r.name} className="flex items-center gap-2">
            <svg width="12" height="8" aria-hidden="true" className="shrink-0">
              {r.kind === "rect" ? (
                <rect x="1" y="0" width="8" height="8" rx="1.5" fill={r.color} />
              ) : (
                <line x1="1" y1="4" x2="11" y2="4" stroke={r.color} strokeWidth="2.5" strokeLinecap="round" />
              )}
            </svg>
            <span className="num font-semibold text-ink">{r.value}</span>
            <span className="text-ink-2">{r.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
