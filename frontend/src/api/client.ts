/**
 * Thin fetch wrapper. All URLs are relative (/api/v1/...) so the same build works behind
 * the Vite dev proxy and behind nginx in the container.
 *
 * The backend returns errors in several shapes; ApiError normalises them:
 *   {"error": {"code", "message", "details": [{loc, msg}]}}      (validation / unhandled)
 *   {"detail": {"code", "message", ...}}                          (HTTPException with dict)
 *   {"detail": "Not Found"}                                       (unknown route)
 *   {"detail": [{loc, msg, type}]}                                 (raw FastAPI validation)
 */

export class ApiError extends Error {
  status: number;
  code?: string;
  details: string[];
  constructor(status: number, message: string, code?: string, details: string[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Json = unknown;

function fmtLoc(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  const parts = loc.filter((p) => p !== "body" && p !== "query" && p !== "path");
  return parts.length ? parts.join(".") + ": " : "";
}

function detailList(items: unknown): string[] {
  if (!Array.isArray(items)) return [];
  return items.map((d) => {
    if (d && typeof d === "object") {
      const o = d as Record<string, unknown>;
      return `${fmtLoc(o.loc)}${String(o.msg ?? o.message ?? JSON.stringify(o))}`;
    }
    return String(d);
  });
}

export function parseError(status: number, body: Json, fallback: string): ApiError {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (b.error && typeof b.error === "object") {
      const e = b.error as Record<string, unknown>;
      return new ApiError(status, String(e.message ?? fallback), e.code as string | undefined, detailList(e.details));
    }
    if (typeof b.detail === "string") return new ApiError(status, b.detail);
    if (Array.isArray(b.detail)) return new ApiError(status, "invalid request", "validation_error", detailList(b.detail));
    if (b.detail && typeof b.detail === "object") {
      const d = b.detail as Record<string, unknown>;
      const extra: string[] = [];
      if (Array.isArray(d.allowed)) extra.push(`allowed: ${d.allowed.join(", ")}`);
      if (Array.isArray(d.active)) extra.push(`active: ${d.active.join(", ")}`);
      if (Array.isArray(d.available)) extra.push(`available: ${d.available.join(", ")}`);
      return new ApiError(status, String(d.message ?? fallback), d.code as string | undefined, extra);
    }
  }
  return new ApiError(status, fallback);
}

export interface RequestOpts {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
}

export async function api<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method ?? "GET",
      headers: opts.body !== undefined ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error)?.name === "AbortError") throw err;
    throw new ApiError(0, "Network error: the AgentShield API is unreachable. Is the backend running?");
  }
  const text = await res.text();
  let body: Json = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const fallback = `${res.status} ${res.statusText || "request failed"}`;
    if (typeof body === "string" && body.trim().startsWith("<")) {
      throw new ApiError(res.status, `${fallback} (upstream returned HTML - the API may be restarting)`);
    }
    throw parseError(res.status, body, fallback);
  }
  return body as T;
}

/** Build a query string, dropping undefined / null / "" values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
