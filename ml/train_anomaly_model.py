"""Train the Isolation Forest anomaly detector on unlabelled reference runs.

    python -m ml.train_anomaly_model --scenarios baseline regression

* Features: robust per-agent-version z-scores of run telemetry (ml/features.py).
* Labels are NOT used for training or threshold selection. The alert threshold
  is the configured quantile of anomaly scores on the training data.
* Saves models/anomaly_iforest_<version>.joblib and models/latest.json
  (model version, features, threshold, baseline profile, training scope).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from common.config import load_thresholds
from common.settings import REPO_ROOT
from ml.features import FEATURES, Baseline, fetch_runs

MODEL_DIR = REPO_ROOT / "models"
CLIP = 50.0


def matrix(df, baseline: Baseline) -> np.ndarray:
    return np.clip(baseline.zscores(df)[FEATURES].fillna(0.0).to_numpy(dtype=float), -CLIP, CLIP)


def train(scenarios: list[str], days: int = 60, out_dir: Path = MODEL_DIR) -> dict:
    cfg = load_thresholds()["isolation_forest"]
    df = fetch_runs(scenarios=scenarios, days=days)
    if len(df) < 500:
        raise SystemExit(f"not enough training runs ({len(df)}) for scenarios {scenarios}")
    baseline = Baseline.fit(df)
    X = matrix(df, baseline)
    model = IsolationForest(n_estimators=cfg["n_estimators"], contamination=cfg["contamination"],
                            random_state=cfg["random_state"], n_jobs=-1).fit(X)
    scores = -model.score_samples(X)  # higher = more anomalous
    threshold = float(np.quantile(scores, cfg["score_threshold_quantile"]))
    trained_at = datetime.now(timezone.utc)
    version = "iforest-" + trained_at.strftime("%Y%m%dT%H%M%S") + "-" + hashlib.sha1(
        ",".join(sorted(df["test_run_id"].unique())).encode()).hexdigest()[:6]
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"anomaly_{version}.joblib"
    joblib.dump(model, model_path)
    meta = {
        "model_version": version,
        "trained_at": trained_at.isoformat(),
        "algorithm": "sklearn.ensemble.IsolationForest",
        "params": cfg,
        "features": FEATURES,
        "feature_transform": "log1p for heavy-tailed features, then robust z-score per agent version, clipped to +/-50",
        "threshold": threshold,
        "threshold_rule": f"quantile {cfg['score_threshold_quantile']} of training anomaly scores (no labels used)",
        "training": {"scenarios": scenarios, "runs": int(len(df)), "test_run_ids": sorted(df["test_run_id"].unique()),
                     "agent_versions": int(len(baseline.stats))},
        "training_score_distribution": {q: float(np.quantile(scores, q)) for q in (0.5, 0.9, 0.99)},
        "operating_points": {str(q): float(np.quantile(scores, q)) for q in cfg.get("report_quantiles", [])},
        "model_file": model_path.name,
        "baseline": baseline.to_json(),
    }
    (out_dir / f"anomaly_{version}.json").write_text(json.dumps(meta, indent=2))
    (out_dir / "latest.json").write_text(json.dumps(meta, indent=2))
    return meta


def load_latest(model_dir: Path = MODEL_DIR) -> tuple[IsolationForest, dict, Baseline]:
    meta_path = model_dir / "latest.json"
    if not meta_path.exists():
        raise FileNotFoundError("no trained model - run: python -m ml.train_anomaly_model")
    meta = json.loads(meta_path.read_text())
    model = joblib.load(model_dir / meta["model_file"])
    return model, meta, Baseline.from_json(meta["baseline"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", nargs="+", default=["baseline", "regression"])
    ap.add_argument("--days", type=int, default=60)
    m = train(ap.parse_args().scenarios, ap.parse_args().days)
    print(json.dumps({k: v for k, v in m.items() if k != "baseline"}, indent=2))
