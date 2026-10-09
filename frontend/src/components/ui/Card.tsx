import type { ReactNode } from "react";
import { Icon } from "./Icon";
import type { TrinoStats } from "../../api/types";
import { fmtBytes, fmtCompact, fmtMs } from "../../lib/format";

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "p-4",
  footer,
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  footer?: ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className={`card flex min-w-0 flex-col ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <div className="mt-0.5 text-xs text-ink-2">{subtitle}</div>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`min-w-0 flex-1 ${bodyClassName}`}>{children}</div>
      {footer && <footer className="border-t border-line px-4 py-2 text-xs text-muted">{footer}</footer>}
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Stat tile: label · value · optional sub-line. Proportional figures (no tabular-nums) for the value. */
export function KpiTile({ label, value, sub, tag, loading }: { label: string; value: ReactNode; sub?: ReactNode; tag?: ReactNode; loading?: boolean }) {
  return (
    <div className="card flex min-w-0 flex-col gap-1 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-ink-2">{label}</span>
        {tag}
      </div>
      {loading ? <div className="skeleton h-7 w-24" /> : <div className="truncate text-2xl font-semibold text-ink">{value}</div>}
      {sub && <div className="truncate text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Note({ tone = "info", children, className = "" }: { tone?: "info" | "warn"; children: ReactNode; className?: string }) {
  const cls = tone === "warn" ? "border-warning/50 bg-warning/10" : "border-accent/30 bg-accent/5";
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs text-ink-2 ${cls} ${className}`}>
      <Icon name={tone === "warn" ? "alert" : "info"} size={14} className={`mt-px shrink-0 ${tone === "warn" ? "text-warning-ink" : "text-accent-ink"}`} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Subtle Trino execution metadata for a query result. */
export function QueryMeta({ elapsed, stats, cached, rowCount, truncated }: { elapsed?: number; stats?: TrinoStats | null; cached?: boolean; rowCount?: number; truncated?: boolean }) {
  const parts: string[] = [];
  if (elapsed !== undefined) parts.push(`Trino ${fmtMs(elapsed)}`);
  if (stats?.processedRows !== undefined) parts.push(`${fmtCompact(stats.processedRows)} rows scanned`);
  if (stats?.processedBytes !== undefined) parts.push(fmtBytes(stats.processedBytes));
  if (rowCount !== undefined) parts.push(`${rowCount.toLocaleString()} result rows${truncated ? " (truncated)" : ""}`);
  if (cached) parts.push("cached");
  if (!parts.length) return null;
  return (
    <span className="num text-2xs text-muted" title={stats ? `cpu ${stats.cpuTimeMillis ?? "?"} ms · wall ${stats.wallTimeMillis ?? "?"} ms · splits ${stats.totalSplits ?? "?"} · peak mem ${fmtBytes(stats.peakMemoryBytes)}` : undefined}>
      {parts.join(" · ")}
    </span>
  );
}

export function Field({ label, children, hint, className = "" }: { label: string; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <span className="label">{label}</span>
      {children}
      {hint && <span className="text-2xs text-muted">{hint}</span>}
    </label>
  );
}

export function KeyValues({ items, cols = 2 }: { items: [string, ReactNode][]; cols?: 1 | 2 | 3 }) {
  const grid = cols === 1 ? "grid-cols-1" : cols === 3 ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-1 sm:grid-cols-2";
  return (
    <dl className={`grid gap-x-4 gap-y-1.5 text-xs ${grid}`}>
      {items.map(([k, v]) => (
        <div key={k} className="flex min-w-0 items-baseline justify-between gap-3 border-b border-line/70 py-1">
          <dt className="shrink-0 text-ink-2">{k}</dt>
          <dd className="num min-w-0 break-words text-right text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
