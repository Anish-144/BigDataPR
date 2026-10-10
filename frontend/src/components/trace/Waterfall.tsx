import { useMemo, useState } from "react";
import type { Span } from "../../api/types";
import { fmtMs } from "../../lib/format";
import { Legend, TooltipBody } from "../charts/ChartFrame";
import { Icon } from "../ui/Icon";

/** Color follows the span kind (entity), never its row position. */
export const KIND_COLOR: Record<string, string> = {
  agent: "var(--series-1)",
  llm_call: "var(--series-2)",
  tool_call: "var(--series-3)",
  retrieval: "var(--series-4)",
  policy_check: "var(--series-5)",
  planning: "var(--series-6)",
  delegation: "var(--series-7)",
};
export const kindColor = (k: string) => KIND_COLOR[k] ?? "var(--deemph)";

export function spanProblem(s: Span): { label: string } | null {
  if (s.policy_decision === "deny") return { label: "denied" };
  if (s.status && s.status !== "ok") return { label: s.status === "timeout" ? "timeout" : s.error_category ?? s.status };
  return null;
}

export interface WfRow {
  span: Span;
  depth: number;
  offsetMs: number;
  orphan: boolean;
  hasChildren: boolean;
  parentId: string | null;
}

export function buildRows(spans: Span[]): { rows: WfRow[]; totalMs: number; t0: number } {
  const t = (iso: string) => new Date(iso).getTime();
  const byId = new Map(spans.map((s) => [s.span_id, s]));
  const children = new Map<string, Span[]>();
  const roots: Span[] = [];
  for (const s of spans) {
    if (s.parent_span_id && byId.has(s.parent_span_id)) {
      const arr = children.get(s.parent_span_id) ?? [];
      arr.push(s);
      children.set(s.parent_span_id, arr);
    } else roots.push(s);
  }
  const order = (a: Span, b: Span) => t(a.start_time) - t(b.start_time) || (a.step_index ?? 0) - (b.step_index ?? 0);
  const t0 = Math.min(...spans.map((s) => t(s.start_time)));
  const t1 = Math.max(...spans.map((s) => Math.max(t(s.end_time ?? s.start_time), t(s.start_time) + (s.duration_ms ?? 0))));
  const rows: WfRow[] = [];
  const seen = new Set<string>();
  const walk = (s: Span, depth: number, orphan: boolean) => {
    if (seen.has(s.span_id)) return;
    seen.add(s.span_id);
    const kids = children.get(s.span_id) ?? [];
    rows.push({ span: s, depth, offsetMs: t(s.start_time) - t0, orphan, hasChildren: kids.length > 0, parentId: s.parent_span_id ?? null });
    kids.sort(order).forEach((c) => walk(c, depth + 1, false));
  };
  roots.sort(order).forEach((r) => walk(r, 0, !!r.parent_span_id));
  return { rows, totalMs: Math.max(1, t1 - t0), t0 };
}

export function Waterfall({ spans, selectedId, onSelect }: { spans: Span[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const { rows, totalMs } = useMemo(() => buildRows(spans), [spans]);
  const [hover, setHover] = useState<{ row: WfRow; x: number; y: number } | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const kinds = useMemo(() => Array.from(new Set(spans.map((s) => s.span_kind))), [spans]);
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  const toggleCollapse = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setCollapsed(next);
  };

  // Filter out children of collapsed parents
  const visibleRows = useMemo(() => {
    const hiddenParents = new Set<string>();
    return rows.filter(r => {
      if (r.parentId && hiddenParents.has(r.parentId)) {
        hiddenParents.add(r.span.span_id);
        return false;
      }
      if (collapsed.has(r.span.span_id)) {
        hiddenParents.add(r.span.span_id);
      }
      return true;
    });
  }, [rows, collapsed]);

  return (
    <div className="flex flex-col gap-3 w-full">
      <div className="flex items-center justify-between px-1">
        <Legend items={kinds.map((k) => ({ label: k, color: kindColor(k) }))} />
        {collapsed.size > 0 && (
          <button type="button" className="text-xs text-accent hover:underline" onClick={() => setCollapsed(new Set())}>
            Expand All
          </button>
        )}
      </div>
      <div className="relative overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
        <div className="min-w-[700px]">
          {/* axis header */}
          <div className="sticky top-0 z-[1] grid grid-cols-[minmax(280px,40%)_72px_1fr] border-b border-line bg-surface-2/90 backdrop-blur-md text-[11px] uppercase tracking-wider font-semibold text-ink-2">
            <div className="px-3 py-2">Span Execution</div>
            <div className="px-2 py-2 text-right">Duration</div>
            <div className="relative h-8">
              {ticks.map((f) => (
                <span
                  key={f}
                  className={`num absolute top-2 whitespace-nowrap ${f === 0 ? "" : f === 1 ? "-translate-x-full" : "-translate-x-1/2"}`}
                  style={{ left: f === 0 ? 8 : f === 1 ? "calc(100% - 8px)" : `${f * 100}%` }}
                >
                  {fmtMs(totalMs * f)}
                </span>
              ))}
            </div>
          </div>
          <ul aria-label="Trace spans" className="relative">
            {visibleRows.map((r) => {
              const s = r.span;
              const left = (r.offsetMs / totalMs) * 100;
              const width = Math.max(0, ((s.duration_ms ?? 0) / totalMs) * 100);
              const problem = spanProblem(s);
              const selected = selectedId === s.span_id;
              const isCollapsed = collapsed.has(s.span_id);

              return (
                <li key={s.span_id}>
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelect(s.span_id)}
                    onFocus={() => onSelect(s.span_id)}
                    className={`grid w-full grid-cols-[minmax(280px,40%)_72px_1fr] items-center border-b border-line/50 text-left text-[13px] last:border-b-0 focus:outline-none focus-visible:bg-surface-2 transition-colors ${selected ? "bg-accent/10 hover:bg-accent/15" : "hover:bg-surface-2/60"}`}
                  >
                    <span className="flex min-w-0 items-center gap-1.5 py-1.5 pr-2 relative" style={{ paddingLeft: 12 + r.depth * 18 }}>
                      
                      {/* Depth Guide Lines */}
                      {Array.from({ length: r.depth }).map((_, i) => (
                        <div key={i} className="absolute top-0 bottom-0 border-l border-line-strong/30" style={{ left: 16 + i * 18 }} />
                      ))}

                      {r.hasChildren ? (
                        <div 
                          className="w-4 h-4 flex items-center justify-center text-ink-2 hover:text-ink hover:bg-surface-2 rounded cursor-pointer z-10 shrink-0" 
                          onClick={(e) => toggleCollapse(s.span_id, e)}
                        >
                          <Icon name={isCollapsed ? "chevronRight" : "chevronDown"} size={14} />
                        </div>
                      ) : (
                        <div className="w-4 h-4 shrink-0" />
                      )}

                      <span aria-hidden="true" className="inline-block h-2.5 w-2.5 shrink-0 rounded-[3px] shadow-sm" style={{ background: kindColor(s.span_kind) }} />
                      
                      <span className={`truncate font-medium ${selected ? 'text-accent-strong' : 'text-ink'}`} title={s.span_name}>
                        {s.span_name}
                      </span>
                      
                      <span className="shrink-0 text-[10px] uppercase font-bold tracking-wider text-muted ml-1">{s.span_kind}</span>
                      
                      {(s.attempt ?? 1) > 1 && (
                        <span className="shrink-0 rounded border border-line-strong bg-surface-2 px-1 text-[10px] font-semibold text-ink-2" title="Retry attempt">
                          try {s.attempt}
                        </span>
                      )}
                      {r.orphan && (
                        <span className="shrink-0 rounded border border-warning/60 bg-warning/10 px-1 text-[10px] font-semibold text-warning-ink" title="Parent span missing">
                          orphan
                        </span>
                      )}
                      {problem && (
                        <span className="inline-flex shrink-0 items-center gap-0.5 text-[11px] font-bold tracking-wide text-critical-ink bg-critical/10 px-1.5 py-0.5 rounded border border-critical/20 ml-1">
                          <Icon name="x" size={10} strokeWidth={3} />
                          {problem.label}
                        </span>
                      )}
                    </span>
                    <span className="num px-2 text-right text-[12px] font-medium text-ink-2">{fmtMs(s.duration_ms)}</span>
                    <span
                      className="relative block h-8"
                      onMouseMove={(e) => setHover({ row: r, x: e.clientX, y: e.clientY })}
                      onMouseLeave={() => setHover(null)}
                    >
                      {ticks.slice(1, -1).map((f) => (
                        <span key={f} aria-hidden="true" className="absolute inset-y-0 w-px bg-line/50" style={{ left: `${f * 100}%` }} />
                      ))}
                      <span
                        className="wf-bar absolute top-1/2 h-3.5 -translate-y-1/2 rounded-[4px] shadow-sm transition-all hover:brightness-110"
                        style={{
                          left: `${left}%`,
                          width: `max(4px, ${width}%)`,
                          background: kindColor(s.span_kind),
                          opacity: problem ? 1 : 0.85,
                          boxShadow: problem ? "0 0 0 2px var(--chart-surface), 0 0 0 3px var(--status-critical)" : undefined,
                        }}
                      />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        {hover && (
          <div className="pointer-events-none fixed z-50 transition-opacity" style={{ left: hover.x + 16, top: hover.y + 16 }}>
            <TooltipBody
              label={`${hover.row.span.span_kind} · ${hover.row.span.status}${spanProblem(hover.row.span) ? " (" + spanProblem(hover.row.span)!.label + ")" : ""}`}
              rows={[
                { name: hover.row.span.span_name, value: fmtMs(hover.row.span.duration_ms), color: kindColor(hover.row.span.span_kind), kind: "rect" },
                { name: "start offset", value: `+${fmtMs(hover.row.offsetMs)}`, color: "var(--chart-axis)" },
              ]}
            />
          </div>
        )}
      </div>
      <p className="text-xs text-muted flex items-center gap-1.5">
        <Icon name="info" size={14} className="opacity-70" />
        Click any row to inspect span attributes. Use arrows to expand/collapse child traces.
      </p>
    </div>
  );
}
