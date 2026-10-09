#!/bin/sh
# Creates the extra databases used by AgentShield and the Iceberg JDBC catalog
# tables. Runs once, on first start of an empty Postgres volume
# (docker-entrypoint-initdb.d).
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER ${ICEBERG_CATALOG_USER} WITH PASSWORD '${ICEBERG_CATALOG_PASSWORD}';
    CREATE DATABASE ${ICEBERG_CATALOG_DB} OWNER ${ICEBERG_CATALOG_USER};
    CREATE USER ${AIRFLOW_DB_USER} WITH PASSWORD '${AIRFLOW_DB_PASSWORD}';
    CREATE DATABASE ${AIRFLOW_DB} OWNER ${AIRFLOW_DB_USER};
EOSQL

PGPASSWORD="${ICEBERG_CATALOG_PASSWORD}" psql -v ON_ERROR_STOP=1 --username "${ICEBERG_CATALOG_USER}" \
    --dbname "${ICEBERG_CATALOG_DB}" -f /docker-entrypoint-initdb.d/iceberg_catalog.sql.inc
echo "agentshield: created databases ${ICEBERG_CATALOG_DB}, ${AIRFLOW_DB} and Iceberg JDBC catalog tables"
