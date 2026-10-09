"""anomaly_model_refresh: retrain the Isolation Forest on unlabelled reference traffic, re-evaluate it on the
labelled holdout scenario (metrics written to benchmarks/results/detector_eval_*.json), then score the last
24 hours of runs with the refreshed model and publish alerts through Kafka."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PY = "cd /opt/agentshield && /opt/agentshield-venv/bin/python -m"
DEFAULT_ARGS = {"owner": "agentshield", "retries": 1, "retry_delay": timedelta(minutes=5),
                "execution_timeout": timedelta(minutes=45)}

with DAG(
    dag_id="anomaly_model_refresh",
    description="Train + evaluate the anomaly detector, then score recent runs",
    schedule="0 3 * * 0",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["agentshield", "ml"],
    doc_md=__doc__,
) as dag:
    train = BashOperator(task_id="train_and_evaluate", bash_command=f"{PY} orchestration.tasks train-and-evaluate")
    score = BashOperator(task_id="score_last_24h", bash_command=f"{PY} orchestration.tasks score-recent --minutes 1440")
    train >> score
