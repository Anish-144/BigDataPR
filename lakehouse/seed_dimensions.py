"""Load dimension/reference tables from config/*.yaml into the lakehouse.

Idempotent: each table is cleared and reloaded. All values are bound as
prepared-statement parameters.

    python -m lakehouse.seed_dimensions
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from common.config import load_agent_catalog, load_policy, load_pricing
from common.settings import REPO_ROOT
from lakehouse.trino_client import connect, wait_for_trino

T = "lakehouse.analytics"


def _exec(cur, sql: str, params: list | None = None) -> None:
    cur.execute(sql, params) if params else cur.execute(sql)
    cur.fetchall()


def seed(verbose: bool = True) -> dict[str, int]:
    conn = connect()
    cur = conn.cursor()
    counts: dict[str, int] = {}
    policy = load_policy()
    now = datetime.now(timezone.utc)

    _exec(cur, f"DELETE FROM {T}.agent_registry")
    n = 0
    for agent in load_agent_catalog():
        ap = policy["agents"].get(agent["agent_id"], {})
        for v in agent["versions"]:
            _exec(cur, f"INSERT INTO {T}.agent_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                agent["agent_id"], agent["agent_name"], agent["workload_type"], agent.get("owner"),
                agent.get("description"), v["version"], int(v["release_seq"]), date.fromisoformat(str(v["released_at"])),
                v["model_name"], v["prompt_version"], list(ap.get("allowed_tools", [])) or None,
                int(ap.get("max_tool_calls", 0)), ap.get("max_data_classification"), json.dumps(v["profile"]), now,
            ])
            n += 1
    counts["agent_registry"] = n

    pricing = load_pricing()
    _exec(cur, f"DELETE FROM {T}.dim_model_pricing")
    for model, p in pricing["models"].items():
        _exec(cur, f"INSERT INTO {T}.dim_model_pricing VALUES (?, ?, ?, ?, ?, ?)", [
            model, float(p["input_per_1k_tokens"]), float(p["output_per_1k_tokens"]), pricing["currency"],
            pricing["pricing_version"], pricing["disclaimer"],
        ])
    counts["dim_model_pricing"] = len(pricing["models"])

    _exec(cur, f"DELETE FROM {T}.dim_policy_rules")
    for r in policy["rules"]:
        _exec(cur, f"INSERT INTO {T}.dim_policy_rules VALUES (?, ?, ?, ?, ?, ?)", [
            r["rule_id"], r["rule_name"], r["category"], r["severity"], r["description"], policy["policy_version"],
        ])
    counts["dim_policy_rules"] = len(policy["rules"])

    _exec(cur, f"DELETE FROM {T}.dim_scenarios")
    scen_dir = REPO_ROOT / "generator" / "scenarios"
    n = 0
    for path in sorted(scen_dir.glob("*.yaml")):
        s = yaml.safe_load(path.read_text(encoding="utf-8"))
        _exec(cur, f"INSERT INTO {T}.dim_scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            s["name"], s.get("description"), int(s.get("seed", 0)), int(s.get("tasks", 0)), s.get("time_mode", "simulated"),
            float(s.get("sim_days", 0) or 0), json.dumps(s.get("workload_mix", [])),
            json.dumps(s.get("fault_profile", {}), sort_keys=True), Path(path).relative_to(REPO_ROOT).as_posix(),
        ])
        n += 1
    counts["dim_scenarios"] = n

    _exec(cur, f"DELETE FROM {T}.dim_date")
    _exec(cur, f"""
        INSERT INTO {T}.dim_date
        SELECT d, year(d), month(d), day(d), day_of_week(d),
               format_datetime(CAST(d AS timestamp), 'EEEE'), day_of_week(d) IN (6, 7)
        FROM UNNEST(sequence(DATE '2026-01-01', DATE '2027-12-31', INTERVAL '1' DAY)) AS t(d)
    """)
    counts["dim_date"] = 730
    conn.close()
    if verbose:
        print("seeded:", counts)
    return counts


if __name__ == "__main__":
    wait_for_trino(float(sys.argv[1]) if len(sys.argv) > 1 else 120)
    seed()
