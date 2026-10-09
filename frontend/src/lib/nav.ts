import type { IconName } from "../components/ui/Icon";

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  /** whether the page honours the global time range (days) */
  timeScoped: boolean;
}

export const NAV: NavItem[] = [
  { path: "/", label: "Overview", icon: "overview", timeScoped: true },
  { path: "/testing", label: "Testing Lab", icon: "lab", timeScoped: false },
  { path: "/runs", label: "Run Explorer", icon: "runs", timeScoped: true },
  { path: "/performance", label: "Performance", icon: "perf", timeScoped: true },
  { path: "/quality", label: "Quality & RAG", icon: "quality", timeScoped: true },
  { path: "/anomalies", label: "Anomaly Center", icon: "anomaly", timeScoped: true },
  { path: "/security", label: "Security & Governance", icon: "security", timeScoped: true },
  { path: "/sql", label: "SQL Analytics", icon: "sql", timeScoped: false },
  { path: "/compare", label: "Agent Comparison", icon: "compare", timeScoped: true },
  { path: "/assistant", label: "Investigation Assistant", icon: "assistant", timeScoped: false },
  { path: "/pipeline", label: "Pipeline Health", icon: "pipeline", timeScoped: true },
  { path: "/reports", label: "Reports", icon: "reports", timeScoped: false },
];

export function navFor(pathname: string): NavItem | undefined {
  if (pathname === "/") return NAV[0];
  return NAV.slice(1).find((n) => pathname === n.path || pathname.startsWith(n.path + "/"));
}
