"""Drop every table in lakehouse.analytics (data + metadata), then recreate the
schema and reseed dimensions. Used by scripts/reset_demo.sh - destructive.

    python -m lakehouse.reset --yes
"""

from __future__ import annotations

import argparse
import sys

from lakehouse import run_sql, seed_dimensions
from lakehouse.trino_client import run_query, wait_for_trino


def drop_all() -> list[str]:
    tables = [r[0] for r in run_query(
        "SELECT table_name FROM lakehouse.information_schema.tables WHERE table_schema = 'analytics'").rows]
    for t in tables:
        if not t.replace("_", "").isalnum():  # names come from the catalog; refuse anything unexpected
            raise ValueError(f"unexpected table name {t!r}")
        run_query(f'DROP TABLE IF EXISTS lakehouse.analytics."{t}"')
    return tables


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="confirm destructive reset")
    args = ap.parse_args()
    if not args.yes:
        print("refusing to reset without --yes", file=sys.stderr)
        return 2
    wait_for_trino(120)
    dropped = drop_all()
    print(f"dropped {len(dropped)} tables")
    rc = run_sql.main(["sql/01_schema_and_tables.sql", "--quiet", "--retries", "3"])
    rc |= run_sql.main(["sql/07_summary_tables.sql", "--quiet"])
    seed_dimensions.seed()
    return rc


if __name__ == "__main__":
    sys.exit(main())
