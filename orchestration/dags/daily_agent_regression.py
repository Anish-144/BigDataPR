"""daily_agent_regression: run the fixed A/B regression suite through the pipeline, wait for it to land,
gate every agent's candidate version against its baseline (results stored in agent_regression_results),
then score the new runs for anomalies. Verdicts are recommendations; promotion is a human decision."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PY = "cd /opt/agentshield && /opt/agentshield-venv/bin/python -m"
DEFAULT_ARGS = {"owner": "agentshield", "retries": 1, "retry_delay": timedelta(minutes=5),
                "execution_timeout": timedelta(minutes=60)}

with DAG(
    dag_id="daily_agent_regression",
    description="Regression suite -> lakehouse -> regression gate -> anomaly scoring",
    schedule="0 1 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["agentshield", "evaluation"],
    doc_md=__doc__,
) as dag:
    suite = BashOperator(
        task_id="run_regression_suite",
        bash_command=f"{PY} orchestration.tasks regression-suite --tasks {{{{ params.tasks }}}}",
        params={"tasks": 8000},
        do_xcom_push=True,  # last stdout line = test_run_id
    )
    gate = BashOperator(
        task_id="regression_gate",
        bash_command=f"{PY} orchestration.tasks regression-gate {{{{ ti.xcom_pull(task_ids='run_regression_suite') }}}}",
    )
    refresh = BashOperator(task_id="refresh_summary_tables",
                           bash_command=f"{PY} lakehouse.run_sql sql/07_summary_tables.sql --quiet --retries 2")
    score = BashOperator(
        task_id="score_regression_runs",
        bash_command=f"{PY} ml.score_events --test-run-id {{{{ ti.xcom_pull(task_ids='run_regression_suite') }}}}",
    )
    suite >> [gate, refresh, score]
