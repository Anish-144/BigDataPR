"""lakehouse_maintenance: data-quality gate -> summary-table refresh + Iceberg compaction -> snapshot expiry."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PY = "cd /opt/agentshield && /opt/agentshield-venv/bin/python -m"
DEFAULT_ARGS = {"owner": "agentshield", "retries": 2, "retry_delay": timedelta(minutes=2),
                "execution_timeout": timedelta(minutes=30)}

with DAG(
    dag_id="lakehouse_maintenance",
    description="Daily data-quality gate, summary-table refresh, Iceberg compaction and snapshot expiry",
    schedule="0 2 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["agentshield", "lakehouse"],
    doc_md=__doc__,
) as dag:
    wait = BashOperator(task_id="wait_for_ingest", bash_command=f"{PY} orchestration.tasks wait-ingest --timeout 1200")
    dq = BashOperator(task_id="data_quality_gate", retries=2,
                      bash_command=f"{PY} lakehouse.maintenance dq-check --max-quarantine-pct 1.0 --days 2")
    summaries = BashOperator(task_id="refresh_summary_tables",
                             bash_command=f"{PY} lakehouse.run_sql sql/07_summary_tables.sql --quiet --retries 2")
    compact = BashOperator(task_id="compact_recent_partitions", bash_command=f"{PY} lakehouse.maintenance compact --days 2")
    expire = BashOperator(task_id="expire_snapshots", bash_command=f"{PY} lakehouse.maintenance expire-snapshots --retention 7d")

    wait >> dq >> [summaries, compact]
    compact >> expire
