import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { NAV, navFor } from "../../lib/nav";
import { DAY_OPTIONS, useDays } from "../../lib/timeRange";
import { usePipelineHealth } from "../../api/hooks";
import { Icon } from "../ui/Icon";
import { componentTone } from "../ui/Badge";

const COLLAPSE_KEY = "agentshield.sidebar";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function Layout() {
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();

  useEffect(() => setDrawer(false), [location.pathname]);

  const toggleCollapsed = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      {/* Desktop sidebar */}
      <aside className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-surface lg:flex ${collapsed ? "w-14" : "w-60"}`}>
        <Brand collapsed={collapsed} />
        <SideNav collapsed={collapsed} />
        <button type="button" onClick={toggleCollapsed} className="m-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-ink-2 hover:bg-surface-2" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <Icon name={collapsed ? "expand" : "collapse"} />
          {!collapsed && "Collapse"}
        </button>
      </aside>

      {/* Mobile / tablet drawer */}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawer(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-surface shadow-xl">
            <div className="flex items-center justify-between pr-2">
              <Brand collapsed={false} />
              <button type="button" className="btn btn-sm" onClick={() => setDrawer(false)} aria-label="Close navigation">
                <Icon name="x" size={14} />
              </button>
            </div>
            <SideNav collapsed={false} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setDrawer(true)} />
        <main id="main" className="mx-auto w-full min-w-0 max-w-[1600px] flex-1 px-4 py-5 lg:px-6">
          <Outlet />
        </main>
        <footer className="border-t border-line px-6 py-3 text-2xs text-muted">
          AgentShield workbench · synthetic, deterministic mock-agent telemetry · costs are estimates from a local pricing table · findings and anomalies are signals for human review, not proof of an attack.
        </footer>
      </div>
    </div>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <Link to="/" className="flex h-14 items-center gap-2 px-3.5 text-ink">
      <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
        <path d="M16 2 4 7v8c0 7.5 5.1 13.4 12 15 6.9-1.6 12-7.5 12-15V7L16 2Z" fill="rgb(var(--accent-strong))" />
        <path d="M10 16.5l4 4 8-9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {!collapsed && (
        <span className="leading-tight">
          <span className="block text-sm font-semibold">AgentShield</span>
          <span className="block text-2xs text-muted">Agent testing workbench</span>
        </span>
      )}
    </Link>
  );
}

function SideNav({ collapsed }: { collapsed: boolean }) {
  return (
    <nav aria-label="Primary" className="flex-1 overflow-y-auto px-2 py-2">
      <ul className="flex flex-col gap-0.5">
        {NAV.map((n) => (
          <li key={n.path}>
            <NavLink
              to={n.path}
              end={n.path === "/"}
              title={collapsed ? n.label : undefined}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm ${isActive ? "bg-accent/10 font-medium text-accent-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`
              }
            >
              <Icon name={n.icon} size={17} className="shrink-0" />
              {!collapsed && <span className="truncate">{n.label}</span>}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const location = useLocation();
  const item = navFor(location.pathname);
  const { days, setDays } = useDays();
  const scoped = item?.timeScoped ?? false;
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface/95 px-4 backdrop-blur lg:px-6">
      <button type="button" className="btn btn-sm lg:hidden" onClick={onMenu} aria-label="Open navigation">
        <Icon name="menu" size={16} />
      </button>
      <div className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{item?.label ?? "AgentShield"}</div>
      <div className="flex items-center gap-2" title={scoped ? "Time range applied to this page" : "This page is not filtered by the global time range"}>
        <span className="hidden text-xs text-ink-2 sm:inline">Range</span>
        <div role="radiogroup" aria-label="Time range" className={`flex rounded-md border border-line-strong p-0.5 ${scoped ? "" : "opacity-50"}`}>
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={days === d}
              onClick={() => setDays(d)}
              className={`num rounded px-2 py-0.5 text-xs font-medium ${days === d ? "bg-accent-strong text-white" : "text-ink-2 hover:bg-surface-2"}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>
      <PipelinePill />
      <ThemeToggle />
    </header>
  );
}

function PipelinePill() {
  const q = usePipelineHealth(30_000);
  const status = q.isError ? "unreachable" : q.data?.status ?? "checking";
  const tone = q.isError ? "critical" : q.data ? componentTone(q.data.status) : "neutral";
  const comps = q.data ? Object.entries(q.data.components) : [];
  const notOk = comps.filter(([, c]) => c && c.status !== "ok").map(([k, c]) => `${k}: ${c!.status}`);
  const dot = { good: "bg-good", warning: "bg-warning", serious: "bg-serious", critical: "bg-critical", neutral: "bg-line-strong", accent: "bg-accent" }[tone];
  const icon = tone === "good" ? "check" : tone === "critical" ? "x" : tone === "warning" ? "alert" : "minus";
  return (
    <Link
      to="/pipeline"
      className="hidden items-center gap-1.5 rounded-full border border-line-strong px-2.5 py-1 text-xs text-ink-2 hover:bg-surface-2 sm:inline-flex"
      title={q.data ? `Pipeline ${q.data.status}${notOk.length ? " - " + notOk.join(", ") : ""} (checked ${new Date(q.data.checked_at).toLocaleTimeString()})` : q.isError ? "Pipeline health endpoint unreachable" : "Checking pipeline…"}
    >
      <span className={`inline-flex h-3.5 w-3.5 items-center justify-center rounded-full text-white ${dot}`}>
        <Icon name={icon} size={9} strokeWidth={3} />
      </span>
      <span>Pipeline</span>
      <span className="font-medium text-ink">{status}</span>
      {notOk.length > 0 && <span className="text-muted">({notOk.length} not ok)</span>}
    </Link>
  );
}

const THEME_KEY = "agentshield.theme";
type Theme = "system" | "light" | "dark";

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem(THEME_KEY);
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const el = document.documentElement;
    if (theme === "system") el.removeAttribute("data-theme");
    else el.setAttribute("data-theme", theme);
    try {
      if (theme === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const icon = theme === "system" ? "monitor" : theme === "light" ? "sun" : "moon";
  return (
    <button type="button" className="btn btn-sm" onClick={() => setTheme(next[theme])} aria-label={`Theme: ${theme}. Switch to ${next[theme]}`} title={`Theme: ${theme} (click to switch)`}>
      <Icon name={icon} size={15} />
    </button>
  );
}
