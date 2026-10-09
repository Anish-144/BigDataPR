# Airflow 2.10 (LocalExecutor, Postgres metadata DB) with AgentShield code in a
# separate virtualenv: Airflow 2.x pins SQLAlchemy < 2.0, AgentShield uses 2.0,
# so DAG tasks call /opt/agentshield-venv/bin/python instead of Airflow's Python.
FROM apache/airflow:2.10.5-python3.12

USER root
RUN mkdir -p /opt/agentshield /opt/agentshield-venv && chown -R airflow:root /opt/agentshield /opt/agentshield-venv
USER airflow

COPY --chown=airflow:root requirements.txt /tmp/agentshield-requirements.txt
RUN python -m venv /opt/agentshield-venv \
 && /opt/agentshield-venv/bin/pip install --no-cache-dir -q -r /tmp/agentshield-requirements.txt

COPY --chown=airflow:root . /opt/agentshield
COPY --chown=airflow:root orchestration/dags /opt/airflow/dags
