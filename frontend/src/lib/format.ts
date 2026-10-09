const DASH = "—";

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function fmtInt(v: unknown): string {
  return isNum(v) ? Math.round(v).toLocaleString("en-US") : DASH;
}

/** 1,284 / 12.9K / 4.2M / 1.9B */
export function fmtCompact(v: unknown): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  if (a < 10_000) return Math.round(v).toLocaleString("en-US");
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function fmtNum(v: unknown, digits = 2): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/** ratio 0..1 -> "81.9%" */
export function fmtPct(v: unknown, digits = 1): string {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : DASH;
}

/** already a percentage number -> "4.42%" */
export function fmtPctRaw(v: unknown, digits = 2): string {
  return isNum(v) ? `${v.toFixed(digits)}%` : DASH;
}

export function fmtMs(v: unknown): string {
  if (!isNum(v)) return DASH;
  if (v === 0) return "0 ms";
  if (Math.abs(v) >= 60_000) return `${(v / 60_000).toFixed(1)} min`;
  if (Math.abs(v) >= 10_000) return `${(v / 1000).toFixed(1)} s`;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)} s`;
  if (Math.abs(v) >= 10) return `${Math.round(v)} ms`;
  return `${v.toFixed(1)} ms`;
}

/** Estimated USD; small values keep significant digits. */
export function fmtUsd(v: unknown): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  if (a === 0) return "$0";
  if (a < 1) return `$${Number(v.toPrecision(2))}`;
  if (a < 1000) return `$${v.toFixed(2)}`;
  return `$${fmtCompact(v)}`;
}

export function fmtBytes(v: unknown): string {
  if (!isNum(v)) return DASH;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let x = v;
  let i = 0;
  while (Math.abs(x) >= 1024 && i < units.length - 1) {
    x /= 1024;
    i++;
  }
  return `${x.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtDateTime(v: unknown): string {
  if (typeof v !== "string" || !v) return DASH;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtHour(v: unknown): string {
  if (typeof v !== "string") return String(v ?? "");
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit" });
}

export function fmtRelative(v: unknown): string {
  if (typeof v !== "string" || !v) return DASH;
  const t = new Date(v).getTime();
  if (Number.isNaN(t)) return String(v);
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 0) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** snake_case -> "Snake case" for column headers. */
export function humanize(key: string): string {
  const s = key
    .replace(/_/g, " ")
    .replace(/\bpct\b/g, "%")
    .replace(/\bms\b/g, "(ms)")
    .replace(/\busd\b/gi, "USD")
    .replace(/\bmrr\b/g, "MRR")
    .replace(/\bf1\b/g, "F1")
    .replace(/ at k\b/g, " @K")
    .replace(/\bdq\b/g, "DQ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Generic cell formatter driven by column name heuristics. */
export function fmtCell(col: string, v: unknown): string {
  if (v === null || v === undefined) return DASH;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : DASH;
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string") {
    if (/(_at|_time|_hour|^hour|^event_hour|_date|first_event|last_event|_ingested|^at)$/.test(col) && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fmtDateTime(v);
    return v;
  }
  if (!isNum(v)) return String(v);
  const c = col.toLowerCase();
  if (/(usd|cost)/.test(c)) return fmtUsd(v);
  if (/bytes/.test(c)) return fmtBytes(v);
  if (/(_pct|pct_|percent)$/.test(c) || c.endsWith("_pct") || c.includes("_pct_")) return fmtPctRaw(v);
  if (/(rate|ratio|accuracy|_acc$|precision|recall|mrr|f1|groundedness|coverage|validity|exact_match|token_f1|^success$|_success$|base_success|cand_success)/.test(c) && v >= 0 && v <= 1)
    return fmtPct(v, 2);
  if (/(_ms$|^ms$|_ms_)/.test(c)) return fmtNum(v, 1);
  if (Number.isInteger(v)) return fmtInt(v);
  return fmtNum(v, 3);
}

export function isNumericColumn(rows: Record<string, unknown>[], col: string): boolean {
  let seen = 0;
  for (const r of rows) {
    const v = r[col];
    if (v === null || v === undefined) continue;
    if (!isNum(v)) return false;
    seen++;
  }
  return seen > 0;
}

export function shortId(id: string | null | undefined, n = 8): string {
  if (!id) return DASH;
  return id.length > n + 2 ? `${id.slice(0, n)}…` : id;
}
