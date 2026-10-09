"""Evaluate the anomaly detectors against synthetic ground truth.

    python -m ml.evaluate_detector --eval-scenario fault_injection --clean-scenario security_suite

* Positives: runs whose injected_faults contain a performance fault or an
  incident window (labels written by the generator; never detector inputs).
* The evaluation scenario is NOT part of the model's training data.
* Reports precision / recall / F1 / false-positive rate per detector family
  (rules, Isolation Forest, combined), recall per fault type, ROC-AUC of the
  Isolation Forest score, and incident-window detection for window rules.
* The clean scenario (no performance faults) measures alert volume on
  traffic without injected performance problems.
Writes benchmarks/results/detector_eval_<timestamp>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from common.settings import get_settings
from ml.features import PERFORMANCE_FAULTS, fetch_runs, labels
from ml.score_events import detect


def prf(y: np.ndarray, p: np.ndarray) -> dict:
    tp = int(((y == 1) & (p == 1)).sum())
    fp = int(((y == 0) & (p == 1)).sum())
    fn = int(((y == 1) & (p == 0)).sum())
    tn = int(((y == 0) & (p == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0}


def predictions(df: pd.DataFrame, dets) -> dict[str, np.ndarray]:
    flagged: dict[str, set] = {"rules": set(), "isolation_forest": set()}
    for d in dets:
        if d.run_index is None:
            continue
        fam = "isolation_forest" if d.detector.startswith("isolation_forest") else "rules"
        flagged[fam].add(d.run_index)
    idx = df.index
    out = {k: np.array([i in v for i in idx], dtype=int) for k, v in flagged.items()}
    out["combined"] = np.maximum(out["rules"], out["isolation_forest"])
    return out


def evaluate(eval_scenario: str, clean_scenario: str | None) -> dict:
    df = fetch_runs(scenarios=[eval_scenario]).reset_index(drop=True)
    y = labels(df).to_numpy()
    dets, meta, scores = detect(df)
    preds = predictions(df, dets)
    result: dict = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model_version": meta["model_version"],
        "model_training_scenarios": meta["training"]["scenarios"],
        "eval_scenario": eval_scenario,
        "eval_runs": int(len(df)),
        "positives": int(y.sum()),
        "overall": {k: prf(y, p) for k, p in preds.items()},
        "isolation_forest_roc_auc": round(float(roc_auc_score(y, scores)), 4) if 0 < y.sum() < len(y) else None,
        "per_fault_recall": {},
        "alerts_by_detector": {},
        "isolation_forest_operating_points": {
            q: {"threshold": thr, **prf(y, (scores > thr).astype(int))}
            for q, thr in meta.get("operating_points", {}).items()},
    }
    for d in dets:
        key = d.detector.split(":")[0] if d.detector.startswith("isolation_forest") else d.detector
        result["alerts_by_detector"][key] = result["alerts_by_detector"].get(key, 0) + 1
    faults = list(PERFORMANCE_FAULTS) + sorted({f for fs in df.injected_faults for f in fs if f.startswith("incident:")})
    for f in faults:
        mask = df.injected_faults.apply(lambda fs, f=f: f in fs).to_numpy()
        if mask.sum() == 0:
            continue
        result["per_fault_recall"][f] = {"runs": int(mask.sum()),
                                         **{k: round(float(p[mask].mean()), 4) for k, p in preds.items()}}

    # incident windows: did a window alert overlap each incident's time range (same agent version)?
    inc = df[df.injected_faults.apply(lambda fs: any(x.startswith("incident:") for x in fs))]
    windows = [d for d in dets if d.run_index is None]
    incidents = []
    for name, g in inc.groupby(inc.injected_faults.apply(lambda fs: next(x for x in fs if x.startswith("incident:")))):
        start, end = g.event_time.min(), g.event_time.max()
        aid, ver = g.agent_id.iloc[0], g.agent_version.iloc[0]
        hit = [w for w in windows if w.agent_id == aid and w.agent_version == ver and w.window_start <= end and w.window_end >= start]
        incidents.append({"incident": name, "agent": f"{aid}@{ver}", "start": str(start), "end": str(end),
                          "runs": int(len(g)), "detected_by_window_rule": bool(hit), "window_alerts": len(hit)})
    false_windows = [w for w in windows if not any(
        i["agent"] == f"{w.agent_id}@{w.agent_version}" and pd.Timestamp(i["start"]) <= w.window_end and pd.Timestamp(i["end"]) >= w.window_start
        for i in incidents)]
    result["incident_windows"] = {"incidents": incidents, "window_alerts_total": len(windows),
                                  "window_alerts_outside_incidents": len(false_windows)}

    if clean_scenario:
        c = fetch_runs(scenarios=[clean_scenario]).reset_index(drop=True)
        yc = labels(c).to_numpy()
        cd, _, _ = detect(c)
        cp = predictions(c, cd)
        result["clean_traffic"] = {"scenario": clean_scenario, "runs": int(len(c)), "runs_with_perf_labels": int(yc.sum()),
                                   **{f"{k}_flag_rate": round(float(p[yc == 0].mean()), 4) for k, p in cp.items()}}
    return result


def render(r: dict) -> str:
    lines = [f"# Anomaly detector evaluation ({r['recorded_at'][:19]}Z)", "",
             f"Model `{r['model_version']}` (trained on {', '.join(r['model_training_scenarios'])}; no labels used). "
             f"Evaluated on held-out scenario `{r['eval_scenario']}`: {r['eval_runs']:,} runs, {r['positives']:,} labelled positives.",
             "", "| Detector | Precision | Recall | F1 | False-positive rate | TP | FP | FN |", "|---|---|---|---|---|---|---|---|"]
    for k, m in r["overall"].items():
        lines.append(f"| {k} | {m['precision']} | {m['recall']} | {m['f1']} | {m['false_positive_rate']} | {m['tp']} | {m['fp']} | {m['fn']} |")
    lines += ["", f"Isolation Forest ROC-AUC (threshold-free): {r['isolation_forest_roc_auc']}", "",
              "Isolation Forest operating points (threshold = training-score quantile; analysis only, not tuned on these labels):",
              "", "| Training quantile | Precision | Recall | F1 |", "|---|---|---|---|"]
    for q, m in r.get("isolation_forest_operating_points", {}).items():
        lines.append(f"| {q} | {m['precision']} | {m['recall']} | {m['f1']} |")
    lines += ["",
              "| Injected fault | Runs | Rules recall | IForest recall | Combined recall |", "|---|---|---|---|---|"]
    for f, m in r["per_fault_recall"].items():
        lines.append(f"| {f} | {m['runs']} | {m['rules']} | {m['isolation_forest']} | {m['combined']} |")
    iw = r["incident_windows"]
    lines += ["", f"Window rule: {sum(i['detected_by_window_rule'] for i in iw['incidents'])}/{len(iw['incidents'])} incident windows "
              f"detected; {iw['window_alerts_outside_incidents']} of {iw['window_alerts_total']} window alerts fell outside incidents."]
    if "clean_traffic" in r:
        c = r["clean_traffic"]
        lines.append(f"Clean traffic (`{c['scenario']}`, {c['runs']:,} runs): flag rate rules {c['rules_flag_rate']}, "
                     f"Isolation Forest {c['isolation_forest_flag_rate']}, combined {c['combined_flag_rate']}.")
    lines += ["", "Limitations: labels mark *injected* faults only; naturally occurring tool errors or slow runs that a detector "
              "flags count as false positives here, so precision is a conservative estimate."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-scenario", default="fault_injection")
    ap.add_argument("--clean-scenario", default="security_suite")
    a = ap.parse_args()
    res = evaluate(a.eval_scenario, a.clean_scenario)
    out = get_settings().results_dir
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"detector_eval_{stamp}.json").write_text(json.dumps(res, indent=2, default=str))
    (out / f"detector_eval_{stamp}.md").write_text(render(res), encoding="utf-8")
    print(render(res))
