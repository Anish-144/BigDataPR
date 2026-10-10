import type { IconName } from "../components/ui/Icon";

/** Base path of the workbench (the landing page owns "/"). Build every in-app link with appPath(). */
export const APP_BASE = "/app";
export const appPath = (path = ""): string => `${APP_BASE}${path}`;

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  /** whether the page honours the global time range (days) */
  timeScoped: boolean;
}

export const NAV: NavItem[] = [
  { path: "/app", label: "Overview", icon: "overview", timeScoped: true },
  { path: "/app/testing", label: "Testing Lab", icon: "lab", timeScoped: false },
  { path: "/app/runs", label: "Run Explorer", icon: "runs", timeScoped: true },
  { path: "/app/performance", label: "Performance", icon: "perf", timeScoped: true },
  { path: "/app/quality", label: "Quality & RAG", icon: "quality", timeScoped: true },
  { path: "/app/anomalies", label: "Anomaly Center", icon: "anomaly", timeScoped: true },
  { path: "/app/security", label: "Security & Governance", icon: "security", timeScoped: true },
  { path: "/app/sql", label: "SQL Analytics", icon: "sql", timeScoped: false },
  { path: "/app/compare", label: "Agent Comparison", icon: "compare", timeScoped: true },
  { path: "/app/assistant", label: "Investigation Assistant", icon: "assistant", timeScoped: false },
  { path: "/app/pipeline", label: "Pipeline Health", icon: "pipeline", timeScoped: true },
  { path: "/app/reports", label: "Reports", icon: "reports", timeScoped: false },
];

export function navFor(pathname: string): NavItem | undefined {
  if (pathname === "/app") return NAV[0];
  return NAV.slice(1).find((n) => pathname === n.path || pathname.startsWith(n.path + "/"));
}
