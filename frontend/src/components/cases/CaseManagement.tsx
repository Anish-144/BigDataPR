import { useState, useMemo, useRef, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  useCases,
  useCase,
  useCaseAnalytics,
  useCreateCase,
  useUpdateCase,
  useAddTimelineNote,
  useAttachEvidence,
  useLinkFinding,
  useDeleteCase,
  useAgents,
} from "../../api/hooks";
import type {
  CaseFilters,
  CasePriority,
  CaseSeverity,
  CaseStatus,
  SecurityCase,
  TimelineEntry,
  CaseEvidenceItem,
  LinkedFinding,
} from "../../api/types";
import { Card, Field, KpiTile, Note } from "../ui/Card";
import { DataTable, Pagination, Select, type Column } from "../ui/DataTable";
import { CaseStatusBadge, PriorityBadge, SeverityBadge, Badge, Tag } from "../ui/Badge";
import { ErrorPanel, EmptyState, SkeletonRows, LoadingBlock } from "../ui/states";
import { Icon } from "../ui/Icon";
import { fmtDateTime, fmtInt, fmtNum } from "../../lib/format";

const LIMIT = 25;

export function CaseManagement() {
  const [sp, setSp] = useSearchParams();
  const selectedCaseId = sp.get("caseId");

  const setSelectedCaseId = (id: string | null) => {
    const next = new URLSearchParams(sp);
    if (id) next.set("caseId", id);
    else next.delete("caseId");
    setSp(next, { replace: true });
  };

  const [filters, setFilters] = useState<CaseFilters>({});
  const [offset, setOffset] = useState(0);
  const [showCreateModal, setShowCreateModal] = useState(false);

  const analytics = useCaseAnalytics(30_000);
  const casesQuery = useCases(filters, LIMIT, offset);
  const agents = useAgents();

  const agentIds = useMemo(
    () => Array.from(new Set(agents.data?.agents.map((a) => a.agent_id) ?? [])),
    [agents.data]
  );

  const setFilter = (k: keyof CaseFilters) => (v: string) => {
    setFilters((prev) => ({ ...prev, [k]: v || undefined }));
    setOffset(0);
  };

  const a = analytics.data;

  const cols: Column<SecurityCase>[] = [
    {
      key: "case_id",
      header: "Case ID",
      render: (r) => (
        <span className="mono font-semibold text-accent-ink hover:underline cursor-pointer">
          {r.case_id}
        </span>
      ),
    },
    {
      key: "title",
      header: "Title",
      render: (r) => (
        <span className="font-medium text-ink max-w-[280px] line-clamp-1" title={r.title}>
          {r.title}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (r) => <CaseStatusBadge status={r.status} />,
    },
    {
      key: "severity",
      header: "Severity",
      render: (r) => <SeverityBadge severity={r.severity} />,
    },
    {
      key: "priority",
      header: "Priority",
      render: (r) => <PriorityBadge priority={r.priority} />,
    },
    {
      key: "agent",
      header: "Target Agent",
      render: (r) => (
        <span className="whitespace-nowrap">
          {r.target_agent.agent_id}{" "}
          <span className="mono text-ink-2 text-2xs">v{r.target_agent.agent_version}</span>
        </span>
      ),
    },
    {
      key: "analyst",
      header: "Assignee",
      render: (r) =>
        r.assigned_analyst?.username ? (
          <span className="text-ink-2 text-xs font-mono">@{r.assigned_analyst.username}</span>
        ) : (
          <span className="text-muted text-xs italic">Unassigned</span>
        ),
    },
    {
      key: "links",
      header: "Findings / Ev",
      align: "center",
      render: (r) => (
        <span className="num text-xs text-ink-2">
          {r.linked_findings?.length ?? 0} f / {r.evidence_bundle?.length ?? 0} ev
        </span>
      ),
    },
    {
      key: "updated_at",
      header: "Updated",
      render: (r) => (
        <span className="whitespace-nowrap text-ink-2 text-2xs">
          {fmtDateTime(r.updated_at)}
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiTile
          label="Total Open Cases"
          value={a ? fmtInt(a.total_open_cases) : "—"}
          sub="active security investigations"
          loading={analytics.isLoading}
        />
        <KpiTile
          label="P1 / Critical"
          value={
            a
              ? fmtInt(
                  (a.priority_breakdown?.P1 ?? 0) + (a.severity_breakdown?.critical ?? 0)
                )
              : "—"
          }
          sub="immediate attention required"
          loading={analytics.isLoading}
        />
        <KpiTile
          label="Unassigned Cases"
          value={a ? fmtInt(a.unassigned_cases) : "—"}
          sub="awaiting analyst triage"
          loading={analytics.isLoading}
        />
        <KpiTile
          label="SLA Breached"
          value={a ? fmtInt(a.sla_breached_cases) : "—"}
          sub="past resolution target"
          tag={
            a && a.sla_breached_cases > 0 ? (
              <Badge tone="critical" icon="alert">
                Action Needed
              </Badge>
            ) : undefined
          }
          loading={analytics.isLoading}
        />
        <KpiTile
          label="MTTR (Hours)"
          value={a?.mttr_hours !== null && a?.mttr_hours !== undefined ? `${fmtNum(a.mttr_hours, 1)}h` : "N/A"}
          sub="mean time to remediation"
          loading={analytics.isLoading}
        />
      </div>

      <Note tone="info">
        <strong>Collaborative Case Management (MongoDB):</strong> High-risk findings and anomalous agent traces are escalated here for collaborative multi-analyst remediation. All mutations maintain an atomic, append-only timeline and link back directly to Lakehouse trace evidence.
      </Note>

      {/* Main Grid: Cases Master Table + Selected Case Detail Drawer */}
      <div className={`grid grid-cols-1 gap-4 ${selectedCaseId ? "2xl:grid-cols-[minmax(0,1fr)_560px]" : ""}`}>
        <Card
          title="Investigation Cases"
          subtitle="Operational lifecycle: triage findings, assign owners, record timeline notes, and verify policy remediation"
          actions={
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setShowCreateModal(true)}
            >
              <Icon name="play" size={12} /> New Case
            </button>
          }
          bodyClassName="p-3"
        >
          {/* Filters */}
          <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
            <Field label="Status">
              <Select
                value={filters.status ?? ""}
                onChange={setFilter("status")}
                options={[
                  { value: "OPEN", label: "Open" },
                  { value: "TRIAGED", label: "Triaged" },
                  { value: "IN_REVIEW", label: "In Review" },
                  { value: "REMEDIATION_PENDING", label: "Remediation Pending" },
                  { value: "RESOLVED", label: "Resolved" },
                  { value: "DISMISSED", label: "Dismissed" },
                ]}
                placeholder="All Statuses"
              />
            </Field>
            <Field label="Severity">
              <Select
                value={filters.severity ?? ""}
                onChange={setFilter("severity")}
                options={["low", "medium", "high", "critical"]}
                placeholder="All Severities"
              />
            </Field>
            <Field label="Priority">
              <Select
                value={filters.priority ?? ""}
                onChange={setFilter("priority")}
                options={["P1", "P2", "P3", "P4"]}
                placeholder="All Priorities"
              />
            </Field>
            <Field label="Target Agent">
              <Select
                value={filters.agent_id ?? ""}
                onChange={setFilter("agent_id")}
                options={agentIds}
                placeholder="All Agents"
              />
            </Field>
            <Field label="Search">
              <input
                className="input text-xs"
                placeholder="Filter by title, ID, tag..."
                value={filters.search ?? ""}
                onChange={(e) => setFilter("search")(e.target.value)}
              />
            </Field>
          </div>

          {casesQuery.isLoading ? (
            <SkeletonRows rows={8} />
          ) : casesQuery.isError && !casesQuery.data ? (
            <ErrorPanel error={casesQuery.error} onRetry={() => casesQuery.refetch()} />
          ) : casesQuery.data ? (
            <>
              <div className={casesQuery.isFetching ? "opacity-60" : ""}>
                <DataTable
                  columns={cols}
                  rows={casesQuery.data.rows}
                  rowKey={(r) => r.case_id}
                  onRowClick={(r) => setSelectedCaseId(r.case_id)}
                  selectedKey={selectedCaseId}
                  dense
                  maxHeight={580}
                  caption="Investigation Cases"
                  empty={<EmptyState title="No security cases match current filters" icon="check" />}
                />
              </div>
              <Pagination
                offset={offset}
                limit={LIMIT}
                count={casesQuery.data.rows.length}
                hasMore={casesQuery.data.has_more}
                fetching={casesQuery.isFetching}
                onChange={setOffset}
              />
            </>
          ) : null}
        </Card>

        {/* Selected Case Detail Drawer */}
        {selectedCaseId && (
          <CaseDetailPanel
            caseId={selectedCaseId}
            onClose={() => setSelectedCaseId(null)}
          />
        )}
      </div>

      {/* Create Case Modal */}
      {showCreateModal && (
        <CreateCaseModal
          agentIds={agentIds}
          onClose={() => setShowCreateModal(false)}
          onCreated={(newCase) => {
            setShowCreateModal(false);
            setSelectedCaseId(newCase.case_id);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Case Detail Drawer Panel
// ---------------------------------------------------------------------------

function CaseDetailPanel({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const caseQuery = useCase(caseId);
  const updateCase = useUpdateCase();
  const addTimeline = useAddTimelineNote();
  const attachEv = useAttachEvidence();
  const linkFinding = useLinkFinding();
  const deleteCase = useDeleteCase();

  const [noteText, setNoteText] = useState("");
  const [noteAction, setNoteAction] = useState("FORENSIC_ANALYSIS");
  const [analystInput, setAnalystInput] = useState("");
  const [showAttachEvidence, setShowAttachEvidence] = useState(false);
  const [evKind, setEvKind] = useState("tool_trace");
  const [evTitle, setEvTitle] = useState("");
  const [evDetail, setEvDetail] = useState("");
  const [evRef, setEvRef] = useState("");
  const [linkFindingId, setLinkFindingId] = useState("");
  const [showLinkFinding, setShowLinkFinding] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (caseQuery.data) {
      setAnalystInput(caseQuery.data.assigned_analyst?.username ?? "");
    }
    containerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [caseId, caseQuery.data?.case_id]);

  if (caseQuery.isLoading) {
    return (
      <Card title="Case Details" bodyClassName="p-4">
        <LoadingBlock height={350} />
      </Card>
    );
  }

  if (caseQuery.isError || !caseQuery.data) {
    return (
      <Card title="Case Details" bodyClassName="p-4">
        <ErrorPanel
          error={caseQuery.error}
          onRetry={() => caseQuery.refetch()}
          title="Could not load case details"
        />
      </Card>
    );
  }

  const c = caseQuery.data;

  const handleStatusChange = (newStatus: string) => {
    updateCase.mutate({
      caseId: c.case_id,
      body: { status: newStatus as CaseStatus, updated_by: "analyst" },
    });
  };

  const handleAssignAnalyst = () => {
    updateCase.mutate({
      caseId: c.case_id,
      body: {
        assigned_analyst: analystInput ? { username: analystInput } : null,
        updated_by: "analyst",
      },
    });
  };

  const handleAddNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    addTimeline.mutate({
      caseId: c.case_id,
      body: {
        action: noteAction,
        notes: noteText.trim(),
        author: "analyst",
      },
    });
    setNoteText("");
  };

  const handleToggleRemediation = () => {
    const isCompleted = !(c.remediation?.completed ?? false);
    updateCase.mutate({
      caseId: c.case_id,
      body: {
        remediation: {
          recommended_action: c.remediation?.recommended_action || "POLICY_PATCH",
          policy_file: c.remediation?.policy_file || "config/policies.yaml",
          target_tool: c.remediation?.target_tool || null,
          completed: isCompleted,
        },
        status: isCompleted ? "RESOLVED" : "IN_REVIEW",
        updated_by: "analyst",
      },
    });
  };

  const handleAttachEvidence = (e: React.FormEvent) => {
    e.preventDefault();
    if (!evTitle.trim()) return;
    attachEv.mutate({
      caseId: c.case_id,
      body: {
        kind: evKind,
        title: evTitle.trim(),
        detail: evDetail.trim(),
        ref: evRef.trim() || undefined,
        author: "analyst",
      },
    });
    setEvTitle("");
    setEvDetail("");
    setEvRef("");
    setShowAttachEvidence(false);
  };

  const handleLinkFinding = (e: React.FormEvent) => {
    e.preventDefault();
    if (!linkFindingId.trim()) return;
    linkFinding.mutate({
      caseId: c.case_id,
      body: {
        finding_id: linkFindingId.trim(),
        rule_id: "SEC-001",
        severity: "medium",
        trace_id: "00000000000000000000000000000000",
        author: "analyst",
      },
    });
    setLinkFindingId("");
    setShowLinkFinding(false);
  };

  return (
    <div ref={containerRef} className="flex flex-col gap-4">
      <Card
        title={
          <div className="flex items-center gap-2">
            <span className="mono font-bold text-accent-ink">{c.case_id}</span>
            <CaseStatusBadge status={c.status} />
          </div>
        }
        subtitle={<span className="line-clamp-1">{c.title}</span>}
        actions={
          <button
            type="button"
            className="btn btn-sm"
            onClick={onClose}
            title="Close drawer"
          >
            <Icon name="x" size={14} /> Close
          </button>
        }
        bodyClassName="p-4 flex flex-col gap-4 text-xs"
      >
        {/* Quick Triage Bar */}
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-line bg-surface-2 p-3 sm:grid-cols-4">
          <div>
            <div className="text-2xs text-muted uppercase font-semibold">Severity</div>
            <div className="mt-1">
              <SeverityBadge severity={c.severity} />
            </div>
          </div>
          <div>
            <div className="text-2xs text-muted uppercase font-semibold">Priority</div>
            <div className="mt-1">
              <PriorityBadge priority={c.priority} />
            </div>
          </div>
          <div>
            <div className="text-2xs text-muted uppercase font-semibold">Target Agent</div>
            <div className="mt-1 font-medium text-ink">
              {c.target_agent.agent_id}{" "}
              <span className="mono text-muted text-2xs">v{c.target_agent.agent_version}</span>
            </div>
          </div>
          <div>
            <div className="text-2xs text-muted uppercase font-semibold">Created By</div>
            <div className="mt-1 text-ink-2 font-mono">@{c.created_by}</div>
          </div>
        </div>

        {/* Lifecycle & Assignment Controls */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Update Case Status">
            <Select
              value={c.status}
              onChange={handleStatusChange}
              options={[
                { value: "OPEN", label: "OPEN" },
                { value: "TRIAGED", label: "TRIAGED" },
                { value: "IN_REVIEW", label: "IN_REVIEW" },
                { value: "REMEDIATION_PENDING", label: "REMEDIATION_PENDING" },
                { value: "RESOLVED", label: "RESOLVED" },
                { value: "DISMISSED", label: "DISMISSED" },
              ]}
              disabled={updateCase.isPending}
            />
          </Field>
          <Field label="Assigned Analyst">
            <div className="flex gap-1.5">
              <input
                className="input text-xs"
                placeholder="analyst_handle"
                value={analystInput}
                onChange={(e) => setAnalystInput(e.target.value)}
              />
              <button
                type="button"
                className="btn btn-sm"
                onClick={handleAssignAnalyst}
                disabled={updateCase.isPending}
              >
                Assign
              </button>
            </div>
          </Field>
        </div>

        {/* Remediation Checklist Card */}
        <div className="rounded-lg border border-line bg-surface p-3 flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink text-xs uppercase tracking-wide">
              Remediation Action Plan
            </span>
            {c.remediation?.completed ? (
              <Badge tone="good" icon="check">
                Completed
              </Badge>
            ) : (
              <Badge tone="warning" icon="diamond">
                Pending Execution
              </Badge>
            )}
          </div>
          <div className="text-xs text-ink-2">
            Action:{" "}
            <span className="font-medium text-ink">
              {c.remediation?.recommended_action || "Apply policy restriction"}
            </span>
            {c.remediation?.target_tool && (
              <span> · Target Tool: <code className="mono">{c.remediation.target_tool}</code></span>
            )}
            {c.remediation?.policy_file && (
              <span> · Policy: <code className="mono">{c.remediation.policy_file}</code></span>
            )}
          </div>
          {c.remediation?.completed && (
            <div className="text-2xs text-good-ink">
              ✓ Verified by @{c.remediation.completed_by} at{" "}
              {fmtDateTime(c.remediation.completed_at)}
            </div>
          )}
          <div className="pt-1">
            <button
              type="button"
              className={`btn btn-sm ${
                c.remediation?.completed ? "btn-danger" : "btn-primary"
              }`}
              onClick={handleToggleRemediation}
              disabled={updateCase.isPending}
            >
              {c.remediation?.completed ? "Reopen Remediation" : "Mark Remediation Complete"}
            </button>
          </div>
        </div>

        {/* Linked Lakehouse Findings & Alerts */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink text-xs uppercase tracking-wide">
              Linked Findings ({c.linked_findings?.length ?? 0})
            </span>
            <button
              type="button"
              className="text-2xs link"
              onClick={() => setShowLinkFinding(!showLinkFinding)}
            >
              {showLinkFinding ? "Cancel" : "+ Link Finding"}
            </button>
          </div>

          {showLinkFinding && (
            <form onSubmit={handleLinkFinding} className="flex gap-2 p-2 border border-line rounded bg-surface-2">
              <input
                className="input text-xs"
                placeholder="Finding ID (e.g. SEC-F-...)"
                value={linkFindingId}
                onChange={(e) => setLinkFindingId(e.target.value)}
              />
              <button type="submit" className="btn btn-sm btn-primary" disabled={linkFinding.isPending}>
                Link
              </button>
            </form>
          )}

          {c.linked_findings?.length ? (
            <div className="flex flex-col gap-1.5 max-h-40 overflow-y-auto pr-1">
              {c.linked_findings.map((f: LinkedFinding) => (
                <div
                  key={f.finding_id}
                  className="flex items-center justify-between gap-2 p-2 rounded border border-line bg-surface-2 text-2xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <SeverityBadge severity={f.severity} />
                    <span className="mono font-medium truncate">{f.rule_id}</span>
                    <span className="text-ink-2 truncate">{f.rule_name}</span>
                  </div>
                  {f.trace_id ? (
                    <Link
                      to={`/app/runs/${f.trace_id}`}
                      className="link whitespace-nowrap"
                    >
                      View Trace →
                    </Link>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-muted italic text-2xs">No findings linked yet.</div>
          )}
        </div>

        {/* Polymorphic Evidence Bundle */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink text-xs uppercase tracking-wide">
              Evidence Attachments ({c.evidence_bundle?.length ?? 0})
            </span>
            <button
              type="button"
              className="text-2xs link"
              onClick={() => setShowAttachEvidence(!showAttachEvidence)}
            >
              {showAttachEvidence ? "Cancel" : "+ Attach Evidence"}
            </button>
          </div>

          {showAttachEvidence && (
            <form onSubmit={handleAttachEvidence} className="flex flex-col gap-2 p-2.5 border border-line rounded bg-surface-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Evidence Kind">
                  <Select
                    value={evKind}
                    onChange={setEvKind}
                    options={[
                      { value: "tool_trace", label: "Tool Trace" },
                      { value: "canary_leak", label: "Canary Leak" },
                      { value: "policy_denial", label: "Policy Denial" },
                      { value: "prompt_injection", label: "Prompt Injection" },
                      { value: "log_diff", label: "Log Diff" },
                      { value: "custom", label: "Custom Artifact" },
                    ]}
                  />
                </Field>
                <Field label="Reference / Span ID">
                  <input
                    className="input text-xs"
                    placeholder="e.g. span:7f3a9c"
                    value={evRef}
                    onChange={(e) => setEvRef(e.target.value)}
                  />
                </Field>
              </div>
              <Field label="Title">
                <input
                  className="input text-xs"
                  placeholder="Short description of evidence"
                  value={evTitle}
                  onChange={(e) => setEvTitle(e.target.value)}
                  required
                />
              </Field>
              <Field label="Details / Payload Preview">
                <textarea
                  className="input text-xs min-h-[60px] py-1.5"
                  placeholder="Extracted telemetry or payload detail..."
                  value={evDetail}
                  onChange={(e) => setEvDetail(e.target.value)}
                />
              </Field>
              <div className="flex justify-end">
                <button type="submit" className="btn btn-sm btn-primary" disabled={attachEv.isPending}>
                  Save Attachment
                </button>
              </div>
            </form>
          )}

          {c.evidence_bundle?.length ? (
            <div className="flex flex-col gap-2 max-h-48 overflow-y-auto pr-1">
              {c.evidence_bundle.map((ev: CaseEvidenceItem) => (
                <div key={ev.evidence_id} className="p-2.5 rounded border border-line bg-surface flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-ink flex items-center gap-1.5">
                      <Tag>{ev.kind}</Tag>
                      {ev.title}
                    </span>
                    <span className="text-2xs text-muted">@{ev.attached_by}</span>
                  </div>
                  {ev.detail && (
                    <div className="text-2xs text-ink-2 bg-surface-2 p-1.5 rounded font-mono break-all whitespace-pre-wrap">
                      {ev.detail}
                    </div>
                  )}
                  {ev.ref && (
                    <div className="text-2xs text-muted">Ref: {ev.ref}</div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-muted italic text-2xs">No evidence attached yet.</div>
          )}
        </div>

        {/* Collaborative Timeline */}
        <div className="flex flex-col gap-2 pt-2 border-t border-line">
          <span className="font-semibold text-ink text-xs uppercase tracking-wide">
            Analyst Collaboration Timeline
          </span>

          <div className="flex flex-col gap-2 max-h-60 overflow-y-auto pr-1">
            {c.timeline?.map((entry: TimelineEntry) => (
              <div key={entry.entry_id} className="flex gap-2.5 text-xs">
                <div className="flex flex-col items-center">
                  <div className="w-2 h-2 rounded-full bg-accent mt-1.5" />
                  <div className="w-px flex-1 bg-line" />
                </div>
                <div className="flex-1 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-ink">@{entry.author}</span>
                    <Badge tone="neutral">{entry.action}</Badge>
                    <span className="text-2xs text-muted">
                      {fmtDateTime(entry.timestamp)}
                    </span>
                  </div>
                  <div className="mt-1 text-ink-2 whitespace-pre-wrap">
                    {entry.notes}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Add Note Form */}
          <form onSubmit={handleAddNote} className="flex flex-col gap-2 pt-2 border-t border-line">
            <div className="flex gap-2">
              <Select
                value={noteAction}
                onChange={setNoteAction}
                options={[
                  { value: "FORENSIC_ANALYSIS", label: "Forensic Analysis" },
                  { value: "NOTE", label: "General Note" },
                  { value: "REMEDIATION_EXECUTED", label: "Remediation Executed" },
                  { value: "STATUS_CHANGE", label: "Status Change" },
                ]}
                className="w-48 text-xs"
              />
              <input
                className="input text-xs flex-1"
                placeholder="Add analyst observation or forensic note..."
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
              />
              <button
                type="submit"
                className="btn btn-sm btn-primary"
                disabled={addTimeline.isPending || !noteText.trim()}
              >
                Post Note
              </button>
            </div>
          </form>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between pt-3 border-t border-line text-2xs text-muted">
          <span>Created {fmtDateTime(c.created_at)}</span>
          <button
            type="button"
            className="text-critical-ink hover:underline cursor-pointer"
            onClick={() => {
              if (window.confirm(`Delete case ${c.case_id}?`)) {
                deleteCase.mutate(c.case_id);
                onClose();
              }
            }}
          >
            Delete Case
          </button>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create Case Modal
// ---------------------------------------------------------------------------

function CreateCaseModal({
  agentIds,
  onClose,
  onCreated,
}: {
  agentIds: string[];
  onClose: () => void;
  onCreated: (newCase: SecurityCase) => void;
}) {
  const createCase = useCreateCase();

  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<CaseSeverity>("high");
  const [priority, setPriority] = useState<CasePriority>("P2");
  const [agentId, setAgentId] = useState(agentIds[0] || "qa-assistant");
  const [agentVersion, setAgentVersion] = useState("1.0.0");
  const [initialNotes, setInitialNotes] = useState("");
  const [recommendedAction, setRecommendedAction] = useState("RESTRICT_TOOL_PERMISSIONS");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMsg("Title is required");
      return;
    }

    try {
      setErrorMsg(null);
      const res = await createCase.mutateAsync({
        title: title.trim(),
        severity,
        priority,
        target_agent: {
          agent_id: agentId,
          agent_version: agentVersion,
        },
        initial_notes: initialNotes.trim() || undefined,
        remediation: {
          recommended_action: recommendedAction,
          policy_file: "config/policies.yaml",
          completed: false,
        },
        created_by: "analyst",
      });
      onCreated(res);
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to create security case");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="card w-full max-w-lg p-6 flex flex-col gap-4 shadow-xl">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="text-base font-semibold text-ink">New Security Investigation Case</h2>
          <button type="button" className="text-muted hover:text-ink" onClick={onClose}>
            <Icon name="x" size={16} />
          </button>
        </div>

        {errorMsg && (
          <div className="p-2 rounded border border-critical/40 bg-critical/10 text-critical-ink text-xs">
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-3 text-xs">
          <Field label="Case Title">
            <input
              className="input text-xs"
              placeholder="e.g. Unauthorized outbound network calls by ops agent"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Severity">
              <Select
                value={severity}
                onChange={(v) => setSeverity(v as CaseSeverity)}
                options={["low", "medium", "high", "critical"]}
              />
            </Field>
            <Field label="Priority">
              <Select
                value={priority}
                onChange={(v) => setPriority(v as CasePriority)}
                options={["P1", "P2", "P3", "P4"]}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Target Agent">
              <Select
                value={agentId}
                onChange={setAgentId}
                options={agentIds.length ? agentIds : [agentId]}
              />
            </Field>
            <Field label="Agent Version">
              <input
                className="input text-xs mono"
                placeholder="1.0.0"
                value={agentVersion}
                onChange={(e) => setAgentVersion(e.target.value)}
                required
              />
            </Field>
          </div>

          <Field label="Recommended Remediation Action">
            <Select
              value={recommendedAction}
              onChange={setRecommendedAction}
              options={[
                { value: "RESTRICT_TOOL_PERMISSIONS", label: "Restrict Tool Permissions" },
                { value: "REVOKE_EGRESS_CAPABILITY", label: "Revoke Egress Capability" },
                { value: "TIGHTEN_SANDBOX_POLICY", label: "Tighten Sandbox Policy" },
                { value: "PROMPT_TEMPLATE_SECURITY_PATCH", label: "Patch Prompt Template" },
                { value: "QUARANTINE_AGENT_VERSION", label: "Quarantine Agent Version" },
              ]}
            />
          </Field>

          <Field label="Initial Forensic Notes">
            <textarea
              className="input text-xs min-h-[70px] py-1.5"
              placeholder="Initial context, symptoms observed in telemetry, or test run reference..."
              value={initialNotes}
              onChange={(e) => setInitialNotes(e.target.value)}
            />
          </Field>

          <div className="flex justify-end gap-2 pt-3 border-t border-line">
            <button type="button" className="btn btn-sm" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-sm btn-primary"
              disabled={createCase.isPending}
            >
              {createCase.isPending ? "Creating..." : "Create Case"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
