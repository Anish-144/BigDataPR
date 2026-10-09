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
    rows.push({ span: s, depth, offsetMs: t(s.start_time) - t0, orphan });
    (children.get(s.span_id) ?? []).sort(order).forEach((c) => walk(c, depth + 1, false));
  };
  roots.sort(order).forEach((r) => walk(r, 0, !!r.parent_span_id));
  return { rows, totalMs: Math.max(1, t1 - t0), t0 };
}

export function Waterfall({ spans, selectedId, onSelect }: { spans: Span[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const { rows, totalMs } = useMemo(() => buildRows(spans), [spans]);
  const [hover, setHover] = useState<{ row: WfRow; x: number; y: number } | null>(null);
  const kinds = useMemo(() => Array.from(new Set(spans.map((s) => s.span_kind))), [spans]);
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="flex flex-col gap-2">
      <Legend items={kinds.map((k) => ({ label: k, color: kindColor(k) }))} />
      <div className="relative overflow-x-auto rounded-md border border-line">
        <div className="min-w-[640px]">
          {/* axis header */}
          <div className="sticky top-0 z-[1] grid grid-cols-[minmax(200px,38%)_64px_1fr] border-b border-line bg-surface-2 text-2xs text-muted">
            <div className="px-2 py-1 font-medium text-ink-2">Span</div>
            <div className="px-1 py-1 text-right font-medium text-ink-2">Duration</div>
            <div className="relative h-6">
              {ticks.map((f) => (
                <span
                  key={f}
                  className={`num absolute top-1 whitespace-nowrap ${f === 0 ? "" : f === 1 ? "-translate-x-full" : "-translate-x-1/2"}`}
                  style={{ left: f === 0 ? 4 : f === 1 ? "calc(100% - 4px)" : `${f * 100}%` }}
                >
                  {fmtMs(totalMs * f)}
                </span>
              ))}
            </div>
          </div>
          <ul aria-label="Trace spans" className="relative">
            {rows.map((r) => {
              const s = r.span;
              const left = (r.offsetMs / totalMs) * 100;
              const width = Math.max(0, ((s.duration_ms ?? 0) / totalMs) * 100);
              const problem = spanProblem(s);
              const selected = selectedId === s.span_id;
              return (
                <li key={s.span_id}>
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelect(s.span_id)}
                    onFocus={() => onSelect(s.span_id)}
                    className={`grid w-full grid-cols-[minmax(200px,38%)_64px_1fr] items-center border-b border-line/60 text-left text-xs last:border-b-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50 ${selected ? "bg-accent/10" : "hover:bg-surface-2"}`}
                  >
                    <span className="flex min-w-0 items-center gap-1.5 py-1 pr-2" style={{ paddingLeft: 8 + r.depth * 14 }}>
                      <span aria-hidden="true" className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: kindColor(s.span_kind) }} />
                      <span className="truncate text-ink" title={s.span_name}>
                        {s.span_name}
                      </span>
                      <span className="shrink-0 text-2xs text-muted">{s.span_kind}</span>
                      {(s.attempt ?? 1) > 1 && (
                        <span className="shrink-0 rounded border border-line-strong px-1 text-2xs text-ink-2" title="Retry attempt">
                          try {s.attempt}
                        </span>
                      )}
                      {r.orphan && (
                        <span className="shrink-0 rounded border border-warning/60 px-1 text-2xs text-warning-ink" title="Parent span missing from the lakehouse (orphan span)">
                          orphan
                        </span>
                      )}
                      {problem && (
                        <span className="inline-flex shrink-0 items-center gap-0.5 text-2xs font-medium text-critical-ink">
                          <Icon name="x" size={11} strokeWidth={2.6} />
                          {problem.label}
                        </span>
                      )}
                    </span>
                    <span className="num px-1 text-right text-2xs text-ink-2">{fmtMs(s.duration_ms)}</span>
                    <span
                      className="relative block h-6"
                      onMouseMove={(e) => setHover({ row: r, x: e.clientX, y: e.clientY })}
                      onMouseLeave={() => setHover(null)}
                    >
                      {ticks.slice(1, -1).map((f) => (
                        <span key={f} aria-hidden="true" className="absolute inset-y-0 w-px bg-line/70" style={{ left: `${f * 100}%` }} />
                      ))}
                      <span
                        className="wf-bar absolute top-1/2 h-3 -translate-y-1/2 rounded-[3px]"
                        style={{
                          left: `${left}%`,
                          width: `max(3px, ${width}%)`,
                          background: kindColor(s.span_kind),
                          opacity: problem ? 1 : 0.9,
                          boxShadow: problem ? "0 0 0 2px var(--chart-surface), 0 0 0 3.5px var(--status-critical)" : undefined,
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
          <div className="pointer-events-none fixed z-50" style={{ left: hover.x + 14, top: hover.y + 12 }}>
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
      <p className="text-2xs text-muted">
        Bars are positioned by start offset from the first span and nested by parent span. A ring and <Icon name="x" size={10} className="inline" /> label mark error,
        timeout and policy-denied spans. Click or tab to a span to inspect it.
      </p>
    </div>
  );
}
