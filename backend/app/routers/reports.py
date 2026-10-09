"""Benchmark / regression report export for a test run (JSON, CSV, Markdown, print-ready HTML)."""

from __future__ import annotations

import csv
import html
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Path, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from backend.app.routers.test_runs import get_test_run
from backend.app.services import query_service as qs

router = APIRouter(prefix="/api/v1", tags=["reports"])
T = "lakehouse.analytics"
DISCLAIMER = ("All values were computed from lakehouse data at generation time. Agent latency/tokens come from deterministic "
              "mock agents (simulated); costs are ESTIMATES from config/pricing.yaml (illustrative local prices). "
              "Security findings and anomaly alerts are signals for human review, not verdicts.")


def build_report(test_run_id: str) -> dict:
    tr = get_test_run(test_run_id)
    p = [test_run_id]
    findings = qs.sql_rows(f"""
        SELECT rule_id, max(rule_name) AS rule_name, severity, count(*) AS findings, count_if(action = 'blocked') AS blocked
        FROM {T}.agent_security_findings WHERE test_run_id = ? GROUP BY rule_id, severity ORDER BY findings DESC""", p)
    alerts = qs.sql_rows(f"""
        SELECT anomaly_type, severity, count(DISTINCT alert_id) AS alerts
        FROM {T}.agent_anomaly_alerts WHERE test_run_id = ? GROUP BY 1, 2 ORDER BY alerts DESC""", p)
    quality = qs.sql_rows(f"""
        SELECT agent_id, agent_version,
               avg(score) FILTER (WHERE metric_name = 'exact_match') AS exact_match,
               avg(score) FILTER (WHERE metric_name = 'schema_validity') AS schema_validity,
               avg(score) FILTER (WHERE metric_name = 'recall_at_k') AS recall_at_k,
               avg(score) FILTER (WHERE metric_name = 'hallucination_flag') AS hallucination_flag_rate
        FROM {T}.agent_evaluation_results WHERE test_run_id = ? AND evaluator_type = 'deterministic'
        GROUP BY 1, 2 ORDER BY 1, 2""", p)
    by_agent = qs.sql_rows(f"""
        SELECT agent_id, agent_version, count(*) AS runs, avg(IF(task_success, 1e0, 0e0)) AS success_rate,
               approx_percentile(latency_ms, 0.5) AS p50_ms, approx_percentile(latency_ms, 0.95) AS p95_ms,
               approx_percentile(latency_ms, 0.99) AS p99_ms, avg(total_tokens) AS avg_tokens,
               sum(estimated_cost_usd) AS est_cost_usd,
               sum(estimated_cost_usd) / nullif(count_if(task_success), 0) AS est_cost_per_success,
               count_if(status <> 'completed') AS failed_runs
        FROM {T}.agent_run_metrics WHERE test_run_id = ? GROUP BY 1, 2 ORDER BY 1, 2""", p)
    return {
        "title": f"AgentShield test-run report {test_run_id}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "test_run": tr["lakehouse"] or tr["operational"],
        "totals": tr["stats"],
        "ingest": tr["ingest"],
        "by_agent_version": by_agent,
        "quality": quality,
        "security_findings": findings,
        "anomaly_alerts": alerts,
        "regression_gates": tr["regression_gates"],
        "disclaimer": DISCLAIMER,
    }


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.4f}" if abs(v) < 10 else f"{v:,.1f}"
    return str(v)


def _table_md(rows: list[dict]) -> str:
    if not rows:
        return "_none_\n"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(_fmt(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out) + "\n"


def to_markdown(r: dict) -> str:
    t = r["totals"]
    parts = [f"# {r['title']}", "", f"Generated {r['generated_at']}", "", f"> {r['disclaimer']}", "",
             "## Totals", "", _table_md([t]), "## Ingestion", "", _table_md([r["ingest"]]),
             "## By agent version", "", _table_md(r["by_agent_version"]), "## Quality (deterministic evaluators)", "",
             _table_md(r["quality"]), "## Security findings", "", _table_md(r["security_findings"]),
             "## Anomaly alerts", "", _table_md(r["anomaly_alerts"]), "## Regression gates", "", _table_md(r["regression_gates"])]
    return "\n".join(parts)


def to_csv(r: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for section in ("by_agent_version", "quality", "security_findings", "anomaly_alerts", "regression_gates"):
        rows = r[section]
        w.writerow([f"# {section}"])
        if rows:
            w.writerow(list(rows[0]))
            for row in rows:
                w.writerow([row[c] for c in rows[0]])
        w.writerow([])
    w.writerow(["# totals"])
    w.writerow(list(r["totals"]))
    w.writerow(list(r["totals"].values()))
    return buf.getvalue()


def to_html(r: dict) -> str:
    def table(rows: list[dict]) -> str:
        if not rows:
            return "<p class='muted'>none</p>"
        cols = list(rows[0])
        head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{html.escape(_fmt(row[c]))}</td>" for c in cols) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    sections = [("Totals", [r["totals"]]), ("Ingestion", [r["ingest"]]), ("By agent version", r["by_agent_version"]),
                ("Quality (deterministic evaluators)", r["quality"]), ("Security findings", r["security_findings"]),
                ("Anomaly alerts", r["anomaly_alerts"]), ("Regression gates", r["regression_gates"])]
    body = "".join(f"<h2>{html.escape(t)}</h2>{table(rows)}" for t, rows in sections)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(r['title'])}</title>
<style>body{{font-family:system-ui,sans-serif;margin:32px;color:#1f2937}}h1{{font-size:22px}}h2{{font-size:16px;margin-top:28px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #d1d5db;padding:4px 6px;text-align:left}}
th{{background:#f3f4f6}}.note{{background:#fffbeb;border:1px solid #fcd34d;padding:8px;font-size:12px}}.muted{{color:#6b7280}}
@media print{{body{{margin:12mm}}}}</style></head><body>
<h1>{html.escape(r['title'])}</h1><p class="muted">Generated {html.escape(r['generated_at'])} - use your browser's Print -> Save as PDF.</p>
<p class="note">{html.escape(r['disclaimer'])}</p>{body}</body></html>"""


@router.get("/reports/{test_run_id}")
def report(test_run_id: str = Path(..., pattern=r"^TR-\d{8}-[0-9a-f]{6}$"),
           format: Literal["json", "csv", "md", "html"] = Query("json")):
    r = build_report(test_run_id)
    name = f"agentshield_report_{test_run_id}"
    if format == "csv":
        return Response(to_csv(r), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if format == "md":
        return PlainTextResponse(to_markdown(r), headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    if format == "html":
        return HTMLResponse(to_html(r))
    return r
