"""Block until the stream processor has drained Kafka into the lakehouse.

Compares the total number of messages in the data topics (Kafka high
watermarks) with the number of rows in raw_agent_events. Because bronze stores
every Kafka record exactly once per offset (valid or not), equality means the
lakehouse is caught up (modulo replays, which would make bronze >= Kafka).

    python -m lakehouse.wait_for_ingest --timeout 900
"""

from __future__ import annotations

import argparse
import sys
import time

from backend.app.services.pipeline_health import kafka_watermarks
from generator.event_schema import DATA_TOPICS
from lakehouse.trino_client import run_query


def kafka_total() -> int:
    hw = kafka_watermarks()
    return sum(sum(p.values()) for t, p in hw.items() if t in {x.value for x in DATA_TOPICS})


def lakehouse_total() -> int:
    return run_query("SELECT count(*) FROM lakehouse.analytics.raw_agent_events").rows[0][0]


def wait(timeout_s: float, quiet: bool = False) -> bool:
    deadline = time.time() + timeout_s
    t0 = time.time()
    while True:
        k, l = kafka_total(), lakehouse_total()
        if not quiet:
            print(f"  kafka={k:,} lakehouse={l:,} ({100 * l / k if k else 100:.1f}%) after {time.time() - t0:.0f}s", flush=True)
        if l >= k:
            return True
        if time.time() > deadline:
            return False
        time.sleep(10)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=900)
    sys.exit(0 if wait(ap.parse_args().timeout) else 1)
