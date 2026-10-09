"""Typed loaders for the YAML configuration in ``config/``."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from common.settings import get_settings


def _load(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or get_settings().config_dir) / name
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class AgentVersion:
    agent_id: str
    agent_name: str
    workload_type: str
    version: str
    release_seq: int
    released_at: str
    model_name: str
    prompt_version: str
    profile: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.agent_id}@{self.version}"


@lru_cache(maxsize=4)
def load_agents(config_dir: Path | None = None) -> dict[str, AgentVersion]:
    """Return ``{"agent_id@version": AgentVersion}``."""
    data = _load("agents.yaml", config_dir)
    out: dict[str, AgentVersion] = {}
    for agent in data["agents"]:
        for v in agent["versions"]:
            av = AgentVersion(
                agent_id=agent["agent_id"],
                agent_name=agent["agent_name"],
                workload_type=agent["workload_type"],
                version=v["version"],
                release_seq=int(v["release_seq"]),
                released_at=str(v["released_at"]),
                model_name=v["model_name"],
                prompt_version=v["prompt_version"],
                profile=dict(v["profile"]),
            )
            out[av.key] = av
    return out


@lru_cache(maxsize=4)
def load_agent_catalog(config_dir: Path | None = None) -> list[dict[str, Any]]:
    return _load("agents.yaml", config_dir)["agents"]


@lru_cache(maxsize=4)
def load_policy(config_dir: Path | None = None) -> dict[str, Any]:
    return _load("policies.yaml", config_dir)


@lru_cache(maxsize=4)
def load_pricing(config_dir: Path | None = None) -> dict[str, Any]:
    return _load("pricing.yaml", config_dir)


@lru_cache(maxsize=4)
def load_thresholds(config_dir: Path | None = None) -> dict[str, Any]:
    return _load("thresholds.yaml", config_dir)


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> tuple[float | None, str]:
    """Estimated cost from the LOCAL pricing table. Returns (cost_or_None, cost_source)."""
    pricing = load_pricing()
    model = pricing.get("models", {}).get(model_name)
    if model is None:
        return None, "unavailable"
    cost = input_tokens / 1000.0 * model["input_per_1k_tokens"] + output_tokens / 1000.0 * model["output_per_1k_tokens"]
    return round(cost, 8), f"local_pricing_config:{pricing['pricing_version']}"
