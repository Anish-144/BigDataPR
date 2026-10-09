"""Score runs with the rule-based and Isolation Forest detectors and publish
alerts to Kafka (topic agent-alerts) using the shared event contract. Spark
lands them in lakehouse.analytics.agent_anomaly_alerts.

    python -m ml.score_events --test-run-id TR-20261009-abc123
    python -m ml.score_events --scenario fault_injection
    python -m ml.score_events --since-minutes 60          # recently ingested runs

Alert IDs are deterministic (detector + run/window + model version), so re-scoring
the same data yields the same IDs (duplicates are detectable, not new alerts).
An anomaly alert is a signal to investigate, not proof of an attack or bug.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from common import ids
from common.settings import get_settings
from generator import event_schema as es
from ml import rules
from ml.features import FEATURES, fetch_runs
from ml.train_anomaly_model import load_latest, matrix

PRODUCER = "agentshield-detector/1.0"


def iforest_detections(df: pd.DataFrame, model, meta: dict, baseline) -> tuple[list[rules.Detection], np.ndarray]:
    X = matrix(df, baseline)
    scores = -model.score_samples(X)
    thr = meta["threshold"]
    z = baseline.zscores(df)[FEATURES]
    out = []
    for pos, (idx, row) in enumerate(df.iterrows()):
        s = float(scores[pos])
        if s <= thr:
            continue
        top = z.loc[idx].abs().sort_values(ascending=False).head(3)
        parts = [f"{f}={row[f]:.4g} (z={z.at[idx, f]:+.1f})" for f in top.index if not np.isnan(z.at[idx, f])]
        margin = s - thr
        sev = "high" if margin >= 0.15 else "medium" if margin >= 0.05 else "low"
        out.append(rules.Detection(
            f"isolation_forest:{meta['model_version']}", "multivariate_outlier", sev, round(s, 4),
            f"Isolation Forest score {s:.3f} exceeds threshold {thr:.3f} for {row.agent_id} {row.agent_version}; "
            f"most unusual features: {', '.join(parts)}",
            {"iforest_score": s, "threshold": thr, **{f"z_{f}": float(z.at[idx, f]) for f in top.index}},
            run_index=idx))
    return out, scores


def to_events(dets: list[rules.Detection], df: pd.DataFrame, model_version: str) -> list[es.AnomalyAlertEvent]:
    events = []
    for d in dets:
        if d.run_index is not None:
            row = df.loc[d.run_index]
            et = row.event_time.to_pydatetime()
            run_id, trace_id, aid, ver = row.run_id, row.trace_id, row.agent_id, row.agent_version
            ws, we, name, tr, scen = et, et, row.agent_name, row.test_run_id, row.scenario_id
            related_runs, related_traces = [run_id], [trace_id]
        else:
            g = df[(df.agent_id == d.agent_id) & (df.agent_version == d.agent_version)]
            run_id = trace_id = None
            aid, ver = d.agent_id, d.agent_version
            ws, we = d.window_start.to_pydatetime(), d.window_end.to_pydatetime()
            et, name = we, (g.agent_name.iloc[0] if len(g) else None)
            tr = g.test_run_id.mode().iloc[0] if len(g) else None
            scen = g.scenario_id.mode().iloc[0] if len(g) else None
            related_runs, related_traces = d.run_ids, d.trace_ids
        version = model_version if d.detector.startswith("isolation_forest") else rules.RULES_VERSION
        alert_id = ids.stable_id(d.detector, run_id or f"{aid}@{ver}@{ws.isoformat()}", version, prefix="A-", n=16)
        rng = ids.task_rng(0, 0, salt=alert_id)
        events.append(es.AnomalyAlertEvent(
            event_id=ids.event_id(rng), event_time=max(et, ws), producer=PRODUCER, test_run_id=tr, run_id=run_id,
            trace_id=trace_id, agent_id=aid, agent_version=ver, scenario_id=scen,
            payload=es.AnomalyAlertPayload(
                alert_id=alert_id, detector=d.detector.split(":")[0] if d.detector.startswith("isolation_forest") else d.detector,
                detector_version=version, anomaly_type=d.anomaly_type, severity=d.severity, score=float(d.score),
                window_start=ws, window_end=we, agent_name=name, related_run_ids=related_runs,
                related_trace_ids=related_traces, supporting_metrics={k: float(v) for k, v in d.supporting.items()},
                explanation=d.explanation,
            ),
        ))
    return events


def detect(df: pd.DataFrame) -> tuple[list[rules.Detection], dict, np.ndarray]:
    model, meta, baseline = load_latest()
    per_run = rules.run_rules(df, baseline)
    windows = rules.window_rules(df, baseline)
    iso, scores = iforest_detections(df, model, meta, baseline)
    return per_run + windows + iso, meta, scores


def existing_alert_ids(alert_ids: list[str]) -> set[str]:
    """Alert ids already stored in the lakehouse (deterministic ids make re-scoring idempotent)."""
    from lakehouse.trino_client import run_query

    found: set[str] = set()
    for i in range(0, len(alert_ids), 500):
        chunk = alert_ids[i:i + 500]
        rows = run_query(f"SELECT DISTINCT alert_id FROM lakehouse.analytics.agent_anomaly_alerts "
                         f"WHERE alert_id IN ({', '.join('?' * len(chunk))})", chunk, max_rows=None).rows
        found.update(r[0] for r in rows)
    return found


def publish(events: list[es.AnomalyAlertEvent], bootstrap: str | None = None) -> int:
    from generator.producer import KafkaSink

    sink = KafkaSink(bootstrap or get_settings().kafka_bootstrap, client_id="agentshield-detector")
    for e in events:
        sink.send(e.topic.value, e.kafka_key().encode(), e.model_dump_json().encode())
    left = sink.flush(60)
    if sink.failed or left:
        raise RuntimeError(f"alert delivery failed: failed={sink.failed} undelivered={left}")
    return sink.delivered


def score(test_run_ids: list[str] | None = None, scenarios: list[str] | None = None, since_minutes: int | None = None,
          publish_alerts: bool = True, bootstrap: str | None = None) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat() if since_minutes else None
    df = fetch_runs(test_run_ids=test_run_ids, scenarios=scenarios, since_iso=since)
    if df.empty:
        return {"runs_scored": 0, "alerts": 0}
    dets, meta, _ = detect(df)
    events = to_events(dets, df, meta["model_version"])
    already = existing_alert_ids([e.payload.alert_id for e in events]) if publish_alerts and events else set()
    new_events = [e for e in events if e.payload.alert_id not in already]
    delivered = publish(new_events, bootstrap) if publish_alerts and new_events else 0
    by_det: dict[str, int] = {}
    for d in dets:
        by_det[d.detector.split(":")[0] if d.detector.startswith("isolation") else d.detector] = \
            by_det.get(d.detector.split(":")[0] if d.detector.startswith("isolation") else d.detector, 0) + 1
    return {"runs_scored": int(len(df)), "alerts": len(events), "already_published": len(already), "published": delivered,
            "by_detector": by_det,
            "model_version": meta["model_version"], "flagged_runs": int(len({d.run_index for d in dets if d.run_index is not None}))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-run-id", action="append")
    ap.add_argument("--scenario", action="append")
    ap.add_argument("--since-minutes", type=int)
    ap.add_argument("--dry-run", action="store_true", help="detect but do not publish alerts")
    a = ap.parse_args()
    print(json.dumps(score(a.test_run_id, a.scenario, a.since_minutes, publish_alerts=not a.dry_run), indent=2))
