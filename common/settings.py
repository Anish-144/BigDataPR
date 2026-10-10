"""Environment-driven settings shared by every Python service.

Defaults target a developer running Python on the host against the Docker
Compose stack (host-mapped ports). They use 127.0.0.1, not "localhost": ports are
bound to IPv4 loopback only, and on Windows "localhost" resolves to ::1 first, which
added ~2 s to every new connection (measured: 2,150 ms vs 75 ms per query).
Containers override them via environment variables defined in docker-compose.yml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    kafka_bootstrap: str = field(default_factory=lambda: _env("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9094"))
    trino_host: str = field(default_factory=lambda: _env("TRINO_HOST", "127.0.0.1"))
    trino_port: int = field(default_factory=lambda: int(_env("TRINO_PORT", "8080")))
    trino_user: str = field(default_factory=lambda: _env("TRINO_USER", "agentshield"))
    trino_catalog: str = field(default_factory=lambda: _env("TRINO_CATALOG", "lakehouse"))
    trino_schema: str = field(default_factory=lambda: _env("TRINO_SCHEMA", "analytics"))
    trino_query_timeout_s: int = field(default_factory=lambda: int(_env("TRINO_QUERY_TIMEOUT_S", "60")))
    postgres_dsn: str = field(
        default_factory=lambda: _env(
            "POSTGRES_DSN", "postgresql+psycopg://agentshield:agentshield@127.0.0.1:5433/agentshield"
        )
    )
    config_dir: Path = field(default_factory=lambda: Path(_env("AGENTSHIELD_CONFIG_DIR", str(REPO_ROOT / "config"))))
    capture_content: bool = field(default_factory=lambda: _env_bool("CAPTURE_CONTENT", False))
    results_dir: Path = field(
        default_factory=lambda: Path(_env("AGENTSHIELD_RESULTS_DIR", str(REPO_ROOT / "benchmarks" / "results")))
    )
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "none"))
    spark_ui_url: str = field(default_factory=lambda: _env("SPARK_UI_URL", "http://localhost:4040"))
    airflow_url: str = field(default_factory=lambda: _env("AIRFLOW_URL", "http://localhost:8088"))


def get_settings() -> Settings:
    return Settings()
