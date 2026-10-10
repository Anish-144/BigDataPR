import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAgents, useFindings, useSecurityPolicy, useSecuritySummary, type FindingFilters } from "../api/hooks";
import type { FindingRow, Row, SecurityPolicy, SecuritySummary } from "../api/types";
import { useDays } from "../lib/timeRange";
import { Card, Field, KpiTile, Note, PageHeader, QueryMeta } from "../components/ui/Card";
import { DataTable, Pagination, Select, Tabs, type Column } from "../components/ui/DataTable";
import { ErrorPanel, EmptyState, LoadingBlock, SkeletonRows } from "../components/ui/states";
import { ResultCard, tableColumns } from "../components/ui/ResultCard";
import { Badge, SeverityBadge, Tag } from "../components/ui/Badge";
import { ChartFrame } from "../components/charts/ChartFrame";
import { BarsChart } from "../components/charts/Charts";
import { fmtDateTime, fmtInt, fmtPctRaw } from "../lib/format";

type TabId = "summary" | "findings" | "policy";
const LIMIT = 25;

export default function Security() {
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") as TabId) || "summary";
  const setTab = (t: TabId) => {
    const n = new URLSearchParams(sp);
    n.set("tab", t);
    setSp(n, { replace: true });
  };
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Security & Governance"
        description="Policy-as-code findings over agent traces: disallowed tools, prohibited actions, prompt-injection indicators, synthetic sensitive-data leaks, privilege transitions and exfiltration-like sequences."
      />
      <Note tone="warn">
        Findings come from deterministic policy rules and content detectors applied to <strong>synthetic</strong> test data (synthetic canary values only). A finding is a
        signal for review, not proof of an attack or malicious intent. Remediation is always human-approved.
      </Note>
      <Tabs
        label="Security sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "summary", label: "Summary" },
          { id: "findings", label: "Findings" },
          { id: "policy", label: "Policy configuration" },
        ]}
      />
      {tab === "summary" && <SummaryTab />}
      {tab === "findings" && <FindingsTab />}
      {tab === "policy" && <PolicyTab />}
    </div>
  );
}

function SummaryTab() {
  const { days } = useDays();
  const q = useSecuritySummary(days);
  if (q.isLoading) return <LoadingBlock height={320} />;
  if (q.isError && !q.data) return <ErrorPanel error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return null;
  return <SummaryBody s={q.data} dimmed={q.isFetching} />;
}

function SummaryBody({ s, dimmed }: { s: SecuritySummary; dimmed: boolean }) {
  const rules = s.by_rule.rows;
  const sum = (k: string) => rules.reduce((a, r) => a + (Number(r[k]) || 0), 0);
  const total = sum("findings");
  const byRule = [...rules].sort((a, b) => Number(b.findings) - Number(a.findings)).map((r) => ({ ...r, label: `${r.rule_id} ${r.rule_name}` }) as Row);
  const gt = s.detection_vs_ground_truth;
  return (
    <div className={`flex flex-col gap-4 ${dimmed ? "opacity-70" : ""}`}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiTile label="Findings" value={fmtInt(total)} sub={`${rules.length} rules triggered`} />
        <KpiTile label="Blocked at runtime" value={fmtInt(sum("blocked"))} sub="tool call denied by the guard" />
        <KpiTile label="Flagged for review" value={fmtInt(sum("flagged"))} sub="allowed but flagged" />
        <KpiTile label="Affected runs" value={fmtInt(sum("affected_runs"))} sub="summed across rules" />
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartFrame
          title="Findings by policy rule"
          subtitle="Count of findings per rule in the selected range"
          table={{ columns: tableColumns(s.by_rule), rows: rules }}
          meta={<QueryMeta elapsed={s.by_rule.elapsed_ms} stats={s.by_rule.trino_stats} cached={s.by_rule.cached} />}
        >
          {byRule.length ? <BarsChart data={byRule} categoryKey="label" series={[{ key: "findings", label: "Findings" }]} horizontal maxCategoryWidth={300} /> : <EmptyState title="No findings in range" icon="check" />}
        </ChartFrame>
        <ChartFrame
          title="Detection rate vs synthetic ground truth"
          subtitle="Share of runs with an injected security scenario that produced a finding of the expected category"
          table={{ columns: tableColumns(gt), rows: gt.rows }}
          meta={<QueryMeta elapsed={gt.elapsed_ms} stats={gt.trino_stats} cached={gt.cached} />}
        >
          {gt.rows.length ? (
            <BarsChart data={gt.rows} categoryKey="injected_scenario" series={[{ key: "detection_rate_pct", label: "Detection rate" }]} horizontal valueFormat={(v) => fmtPctRaw(v, 0)} valueDomain={[0, 100]} />
          ) : (
            <EmptyState title="No labelled security scenarios in range" />
          )}
        </ChartFrame>
      </div>
      <Note>
        "Same-category findings on unlabelled runs" (table view of the chart above) counts findings where no fault was injected - the closest thing to a false-positive
        count for these rules on synthetic data.
      </Note>
      <ResultCard result={s.highest_risk} title="Highest-risk scenarios (findings per 1,000 runs)" subtitle="NTILE risk quartile over scenario × agent version" />
      <Card title="Findings by agent version" bodyClassName="p-3">
        {s.by_agent.length ? (
          <DataTable
            dense
            clientSort
            maxHeight="none"
            rows={s.by_agent as unknown as Row[]}
            rowKey={(r) => `${r.agent_id}@${r.agent_version}`}
            columns={[
              { key: "agent_id", header: "Agent" },
              { key: "agent_version", header: "Version", render: (r) => <span className="mono">{String(r.agent_version)}</span> },
              { key: "findings", header: "Findings", align: "right", render: (r) => fmtInt(r.findings) },
              { key: "critical", header: "Critical", align: "right", render: (r) => fmtInt(r.critical) },
              { key: "blocked", header: "Blocked", align: "right", render: (r) => fmtInt(r.blocked) },
              { key: "affected_runs", header: "Affected runs", align: "right", render: (r) => fmtInt(r.affected_runs) },
            ]}
          />
        ) : (
          <EmptyState title="No findings in range" icon="check" />
        )}
      </Card>
    </div>
  );
}

function FindingsTab() {
  const { days } = useDays();
  const [filters, setFilters] = useState<FindingFilters>({});
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [filters, days]);
  const q = useFindings(days, filters, LIMIT, offset);
  const policy = useSecurityPolicy();
  const agents = useAgents();
  const rules = policy.data?.policy.rules ?? [];
  const categories = useMemo(() => Array.from(new Set(rules.map((r) => r.category))), [rules]);
  const agentIds = useMemo(() => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])), [agents.data]);
  const set = (k: keyof FindingFilters) => (v: string) => setFilters((f) => ({ ...f, [k]: v || undefined }));

  const cols: Column<FindingRow>[] = [
    { key: "event_time", header: "Time", render: (r) => <span className="whitespace-nowrap text-ink-2">{fmtDateTime(r.event_time)}</span> },
    { key: "severity", header: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> },
    {
      key: "rule",
      header: "Rule",
      render: (r) => (
        <span title={r.rule_description ?? undefined}>
          <span className="font-medium">{r.rule_id}</span> <span className="text-ink-2">{r.rule_name}</span>
        </span>
      ),
    },
    {
      key: "action",
      header: "Action",
      render: (r) => (
        <Badge tone={r.action === "blocked" ? "accent" : "neutral"} icon={r.action === "blocked" ? "stop" : "flag"}>
          {r.action}
        </Badge>
      ),
    },
    { key: "agent", header: "Agent", render: (r) => <span className="whitespace-nowrap">{r.agent_id} <span className="mono text-ink-2">{r.agent_version}</span></span> },
    {
      key: "span",
      header: "Span evidence",
      render: (r) => (
        <span className="flex flex-col">
          <span className="mono">{r.span_name ?? "—"}</span>
          <span className="text-2xs text-muted">
            {r.span_kind ?? ""} {r.policy_decision ? `· ${r.policy_decision}` : ""} {r.data_classification ? `· ${r.data_classification}` : ""}
          </span>
        </span>
      ),
    },
    { key: "evidence", header: "Evidence", className: "max-w-[360px] break-words text-ink-2" },
    {
      key: "trace",
      header: "Trace",
      render: (r) =>
        r.trace_id ? (
          <Link className="link whitespace-nowrap" to={`/app/runs/${r.trace_id}`} onClick={(e) => e.stopPropagation()}>
            {r.run_id ?? "open"} →
          </Link>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <Card title="Security findings" subtitle="Each finding links to the span evidence in its trace" bodyClassName="p-3">
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Field label="Severity">
          <Select value={filters.severity ?? ""} onChange={set("severity")} options={["low", "medium", "high", "critical"]} placeholder="Any" />
        </Field>
        <Field label="Rule">
          <Select value={filters.rule_id ?? ""} onChange={set("rule_id")} options={rules.map((r) => ({ value: r.rule_id, label: `${r.rule_id} ${r.rule_name}` }))} placeholder="Any" />
        </Field>
        <Field label="Category">
          <Select value={filters.category ?? ""} onChange={set("category")} options={categories} placeholder="Any" />
        </Field>
        <Field label="Action">
          <Select value={filters.action ?? ""} onChange={set("action")} options={["blocked", "flagged"]} placeholder="Any" />
        </Field>
        <Field label="Agent">
          <Select value={filters.agent_id ?? ""} onChange={set("agent_id")} options={agentIds} placeholder="Any" />
        </Field>
        <Field label="Test run id">
          <input className="input mono" placeholder="TR-…" value={filters.test_run_id ?? ""} onChange={(e) => set("test_run_id")(e.target.value.trim())} />
        </Field>
      </div>
      {q.isLoading ? (
        <SkeletonRows rows={8} />
      ) : q.isError && !q.data ? (
        <ErrorPanel error={q.error} onRetry={() => q.refetch()} />
      ) : q.data ? (
        <>
          <div className={q.isFetching ? "opacity-60" : ""}>
            <DataTable columns={cols} rows={q.data.rows} rowKey={(r) => r.finding_id} dense maxHeight={620} caption="Security findings" empty={<EmptyState title="No findings match these filters" icon="search" />} />
          </div>
          <Pagination offset={offset} limit={LIMIT} count={q.data.rows.length} hasMore={q.data.has_more} fetching={q.isFetching} onChange={setOffset} />
        </>
      ) : null}
    </Card>
  );
}

function PolicyTab() {
  const q = useSecurityPolicy();
  if (q.isLoading) return <LoadingBlock height={300} />;
  if (q.isError && !q.data) return <ErrorPanel error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return null;
  return <PolicyBody p={q.data} />;
}

function TagList({ items, mono = true }: { items?: string[]; mono?: boolean }) {
  if (!items?.length) return <span className="text-muted">none</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((t) => (
        <span key={t} className={`rounded border border-line bg-surface-2 px-1.5 py-px text-2xs text-ink ${mono ? "font-mono" : ""}`}>
          {t}
        </span>
      ))}
    </span>
  );
}

function PolicyBody({ p }: { p: SecurityPolicy }) {
  const pol = p.policy;
  const agents = Object.entries(pol.agents ?? {}).map(([agent_id, v]) => ({ agent_id, ...v }));
  return (
    <div className="flex flex-col gap-4">
      <Card
        title={`Policy version ${pol.policy_version}`}
        subtitle={
          <>
            Policy-as-code loaded from <span className="mono">{p.source ?? "policy file"}</span>. {p.note}
          </>
        }
        bodyClassName="p-3"
      >
        <div className="label mb-2">Per-agent tool allowlists</div>
        <DataTable
          dense
          maxHeight="none"
          rows={agents}
          rowKey={(r) => r.agent_id}
          columns={[
            { key: "agent_id", header: "Agent", render: (r) => <span className="font-medium">{r.agent_id}</span> },
            { key: "allowed_tools", header: "Allowed tools", render: (r) => <TagList items={r.allowed_tools} /> },
            { key: "max_tool_calls", header: "Max tool calls", align: "right", render: (r) => fmtInt(r.max_tool_calls) },
            { key: "max_data_classification", header: "Max data classification", render: (r) => <Tag>{r.max_data_classification}</Tag> },
            { key: "runtime_role", header: "Runtime role", render: (r) => <span className="mono">{r.runtime_role}</span> },
          ]}
        />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Globally prohibited tools">
          <TagList items={pol.prohibited_tools} />
        </Card>
        <Card title="Egress tools (exfiltration sequence detection)">
          <TagList items={pol.egress_tools} />
        </Card>
        <Card title="Restricted resources">
          <TagList items={pol.restricted_resources} />
        </Card>
        <Card title="Data classifications (ascending)">
          <TagList items={pol.data_classifications} mono={false} />
        </Card>
        <Card title="Sensitive-data patterns (synthetic canaries)">
          <ul className="flex flex-col gap-1 text-xs">
            {(pol.sensitive_patterns ?? []).map((s) => (
              <li key={s.name} className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium text-ink">{s.name}</span>
                <code className="mono rounded bg-surface-2 px-1 text-ink-2">{s.regex}</code>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Prompt-injection indicators (regex)">
          <ul className="flex flex-col gap-1 text-xs">
            {(pol.prompt_injection_indicators ?? []).map((s) => (
              <li key={s}>
                <code className="mono rounded bg-surface-2 px-1 text-ink-2">{s}</code>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Privilege model">
          <div className="flex flex-col gap-2 text-xs">
            <div>
              Expected runtime role: <span className="mono text-ink">{pol.privilege?.expected_role ?? "—"}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              Elevated roles: <TagList items={pol.privilege?.elevated_roles} />
            </div>
          </div>
        </Card>
      </div>
      <Card title="Detection rules" bodyClassName="p-3">
        <DataTable
          dense
          maxHeight="none"
          rows={pol.rules ?? []}
          rowKey={(r) => r.rule_id}
          columns={[
            { key: "rule_id", header: "Rule", render: (r) => <span className="font-medium">{r.rule_id}</span> },
            { key: "rule_name", header: "Name" },
            { key: "category", header: "Category", render: (r) => <span className="mono">{r.category}</span> },
            { key: "severity", header: "Severity", render: (r) => <SeverityBadge severity={r.severity} /> },
            { key: "description", header: "Description", className: "text-ink-2" },
          ]}
        />
      </Card>
    </div>
  );
}
