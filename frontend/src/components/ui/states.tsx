import type { CSSProperties, ReactNode } from "react";
import { ApiError } from "../../api/client";
import { Icon } from "./Icon";

export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />;
}

export function LoadingBlock({ label = "Loading…", height = 160 }: { label?: string; height?: number }) {
  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-2" style={{ minHeight: height }}>
      <span className="sr-only">{label}</span>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="w-full flex-1" style={{ minHeight: height - 28 }} />
    </div>
  );
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-2">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}

export function ErrorPanel({ error, onRetry, title = "Could not load data" }: { error: unknown; onRetry?: () => void; title?: string }) {
  const e = error as ApiError | Error | undefined;
  const status = e instanceof ApiError ? e.status : undefined;
  const details = e instanceof ApiError ? e.details : [];
  const code = e instanceof ApiError ? e.code : undefined;
  return (
    <div role="alert" className="rounded-md border border-critical/40 bg-critical/5 p-3 text-sm">
      <div className="flex items-start gap-2">
        <Icon name="alert" className="mt-0.5 shrink-0 text-critical-ink" />
        <div className="min-w-0 flex-1">
          <div className="font-medium text-ink">{title}</div>
          <div className="mt-0.5 break-words text-ink-2">
            {status ? <span className="mono mr-1 text-muted">HTTP {status}{code ? ` · ${code}` : ""}</span> : null}
            {e?.message ?? "Unknown error"}
          </div>
          {details.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-ink-2">
              {details.map((d, i) => (
                <li key={i} className="break-words">{d}</li>
              ))}
            </ul>
          )}
        </div>
        {onRetry && (
          <button type="button" className="btn btn-sm shrink-0" onClick={onRetry}>
            <Icon name="refresh" size={14} /> Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, icon = "info" }: { title: string; children?: ReactNode; icon?: "info" | "search" | "check" }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-line-strong px-4 py-8 text-center">
      <Icon name={icon} size={20} className="text-muted" />
      <div className="text-sm font-medium text-ink">{title}</div>
      {children && <div className="max-w-md text-xs text-ink-2">{children}</div>}
    </div>
  );
}

/** Standard query-state switch: loading skeleton -> error panel -> empty -> content. */
export function QueryState<T>({
  query,
  children,
  isEmpty,
  empty,
  loading,
  errorTitle,
}: {
  query: { data: T | undefined; isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  loading?: ReactNode;
  errorTitle?: string;
}) {
  if (query.isLoading) return <>{loading ?? <LoadingBlock />}</>;
  if (query.isError && query.data === undefined) return <ErrorPanel error={query.error} onRetry={() => query.refetch()} title={errorTitle} />;
  if (query.data === undefined) return <>{loading ?? <LoadingBlock />}</>;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="No data for this selection" />}</>;
  return <>{children(query.data)}</>;
}
