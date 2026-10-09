import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

/**
 * Status colors are reserved for state (good / warning / serious / critical) and always
 * ship with an icon + text label - never color alone.
 */
export type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "accent";

const TONE: Record<Tone, string> = {
  good: "border-good/40 bg-good/10 text-good-ink",
  warning: "border-warning/50 bg-warning/15 text-warning-ink",
  serious: "border-serious/50 bg-serious/15 text-serious-ink",
  critical: "border-critical/40 bg-critical/10 text-critical-ink",
  neutral: "border-line-strong bg-surface-2 text-ink-2",
  accent: "border-accent/40 bg-accent/10 text-accent-ink",
};
const TONE_ICON: Record<Tone, IconName> = {
  good: "check",
  warning: "alert",
  serious: "diamond",
  critical: "x",
  neutral: "minus",
  accent: "info",
};

export function Badge({ tone = "neutral", icon, children, title }: { tone?: Tone; icon?: IconName | null; children: ReactNode; title?: string }) {
  const ic = icon === null ? null : icon ?? TONE_ICON[tone];
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-2xs font-medium ${TONE[tone]}`}>
      {ic && <Icon name={ic} size={11} strokeWidth={2.4} />}
      {children}
    </span>
  );
}

export function severityTone(sev: string | null | undefined): Tone {
  switch ((sev ?? "").toLowerCase()) {
    case "critical":
      return "critical";
    case "high":
      return "serious";
    case "medium":
      return "warning";
    case "low":
    case "info":
      return "neutral";
    default:
      return "neutral";
  }
}

export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  return <Badge tone={severityTone(severity)}>{severity ?? "unknown"}</Badge>;
}

export function componentTone(status: string | null | undefined): Tone {
  switch ((status ?? "").toLowerCase()) {
    case "ok":
    case "running":
    case "completed":
    case "passed":
    case "pass":
      return "good";
    case "degraded":
    case "review":
    case "needs_review":
    case "queued":
    case "stopped":
      return "warning";
    case "down":
    case "failed":
    case "fail":
    case "error":
    case "timeout":
      return "critical";
    default:
      return "neutral";
  }
}

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  const s = status ?? "unknown";
  const tone = componentTone(s);
  const icon: IconName = s === "unknown" ? "question" : tone === "good" ? "check" : tone === "critical" ? "x" : tone === "warning" ? "alert" : "minus";
  return (
    <Badge tone={tone} icon={icon}>
      {label ?? s}
    </Badge>
  );
}

export function VerdictBadge({ verdict, large = false }: { verdict: string; large?: boolean }) {
  const map: Record<string, { tone: Tone; icon: IconName; label: string }> = {
    PASSED: { tone: "good", icon: "check", label: "Passed" },
    NEEDS_REVIEW: { tone: "warning", icon: "alert", label: "Needs review" },
    FAILED: { tone: "critical", icon: "x", label: "Failed" },
    INSUFFICIENT_DATA: { tone: "neutral", icon: "question", label: "Insufficient data" },
  };
  const m = map[verdict] ?? { tone: "neutral" as Tone, icon: "question" as IconName, label: verdict };
  if (!large) return <Badge tone={m.tone} icon={m.icon}>{m.label}</Badge>;
  return (
    <span className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-base font-semibold ${TONE[m.tone]}`}>
      <Icon name={m.icon} size={18} strokeWidth={2.4} />
      {m.label}
    </span>
  );
}

export function SuccessBadge({ success }: { success: boolean | null | undefined }) {
  if (success === null || success === undefined) return <Badge>n/a</Badge>;
  return success ? <Badge tone="good">success</Badge> : <Badge tone="critical">unsuccessful</Badge>;
}

/** Small neutral tag, e.g. "simulated", "est.", "deterministic". */
export function Tag({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center rounded border border-line bg-surface-2 px-1.5 py-px text-2xs font-medium text-ink-2">
      {children}
    </span>
  );
}
