"""AgentShield workload runner + Kafka producer.

Usage (host, against the Docker stack):
    python -m generator.producer --scenario generator/scenarios/smoke.yaml
    python -m generator.producer --scenario generator/scenarios/baseline.yaml --tasks 50000 --workers 6
    python -m generator.producer --scenario ... --sink jsonl:out.jsonl   # offline, no Kafka
    python -m generator.producer --scenario ... --sink null              # generation speed only

Writes a measured summary to benchmarks/results/generator_<test_run_id>.json.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil

from common import ids
from common.settings import get_settings
from generator import event_schema as es
from generator.runner import PRODUCER, TestRunConfig, execute_task, make_context, test_run_event
from ingestion.validation import DirtyDataInjector, dead_letter

RESOURCE_INTERVAL_S = 5.0


# --------------------------------------------------------------------------- sinks


class KafkaSink:
    def __init__(self, bootstrap: str, client_id: str):
        from confluent_kafka import Producer

        self.producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                "client.id": client_id,
                "acks": "all",
                "enable.idempotence": True,
                "compression.type": "lz4",
                "linger.ms": 25,
                "batch.num.messages": 10000,
                "queue.buffering.max.messages": 400000,
                "queue.buffering.max.kbytes": 262144,
                "message.timeout.ms": 120000,
                "retry.backoff.ms": 250,
            }
        )
        self.sent = 0
        self.delivered = 0
        self.failed = 0
        self.errors: Counter[str] = Counter()

    def _on_delivery(self, err, msg) -> None:  # called from poll()/flush()
        if err is not None:
            self.failed += 1
            self.errors[err.name()] += 1
        else:
            self.delivered += 1

    def send(self, topic: str, key: bytes, value: bytes) -> None:
        while True:
            try:
                self.producer.produce(topic, value=value, key=key, on_delivery=self._on_delivery)
                break
            except BufferError:
                self.producer.poll(0.05)  # local queue full: serve delivery callbacks and retry
        self.sent += 1
        if self.sent % 1000 == 0:
            self.producer.poll(0)

    def flush(self, timeout: float = 120.0) -> int:
        return self.producer.flush(timeout)

    def stats(self) -> dict[str, Any]:
        return {"sent": self.sent, "delivered": self.delivered, "failed": self.failed, "errors": dict(self.errors)}


class JsonlSink:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")
        self.lock = threading.Lock()
        self.sent = 0

    def send(self, topic: str, key: bytes, value: bytes) -> None:
        line = json.dumps({"topic": topic, "key": key.decode(), "value": value.decode("utf-8", "replace")})
        with self.lock:
            self.fh.write(line + "\n")
        self.sent += 1

    def flush(self, timeout: float = 0) -> int:
        self.fh.flush()
        return 0

    def stats(self) -> dict[str, Any]:
        return {"sent": self.sent, "delivered": self.sent, "failed": 0, "errors": {}}


class NullSink:
    def __init__(self) -> None:
        self.sent = 0

    def send(self, topic: str, key: bytes, value: bytes) -> None:
        self.sent += 1

    def flush(self, timeout: float = 0) -> int:
        return 0

    def stats(self) -> dict[str, Any]:
        return {"sent": self.sent, "delivered": self.sent, "failed": 0, "errors": {}}


def make_sink(spec: str, bootstrap: str, client_id: str):
    if spec == "kafka":
        return KafkaSink(bootstrap, client_id)
    if spec == "null":
        return NullSink()
    if spec.startswith("jsonl:"):
        return JsonlSink(spec.split(":", 1)[1])
    raise ValueError(f"unknown sink {spec!r}")


# --------------------------------------------------------------------------- workers


def _send_event(sink, event: es._EnvelopeBase, dirty: DirtyDataInjector | None, counts: Counter) -> int:
    value = event.model_dump_json().encode()
    payloads = dirty.apply(event.event_type, value) if dirty else [value]
    for v in payloads:
        sink.send(event.topic.value, event.kafka_key().encode(), v)
    counts[event.event_type] += 1
    return len(payloads)


def worker_main(cfg_json: str, test_run_id: str, worker_idx: int, sink_spec: str, bootstrap: str,
                stop_event, progress, result_queue) -> None:
    cfg = TestRunConfig.model_validate_json(cfg_json)
    ctx = make_context(cfg, test_run_id)
    worker_id = f"{test_run_id}-w{worker_idx}"
    sink = make_sink(sink_spec, bootstrap, client_id=worker_id)
    dirty = (DirtyDataInjector(cfg.dirty_rate, seed=cfg.seed * 1000 + worker_idx, kinds=cfg.dirty_kinds)
             if cfg.dirty_rate > 0 else None)
    proc = psutil.Process()
    proc.cpu_percent(None)
    counts: Counter[str] = Counter()
    emitted = tasks_done = task_errors = 0
    last_report, last_emitted = time.perf_counter(), 0
    per_worker_rate = cfg.rate_per_sec / cfg.workers if cfg.rate_per_sec > 0 else 0.0
    t0 = time.perf_counter()
    rng = ids.task_rng(cfg.seed, -3, salt=worker_id)

    for i in range(worker_idx, cfg.tasks, cfg.workers):
        if stop_event is not None and stop_event.is_set():
            break
        try:
            events = execute_task(ctx, i, worker_id)
        except Exception as exc:  # contract violation or simulator bug -> dead-letter, never silently dropped
            task_errors += 1
            d = dead_letter(json.dumps({"task_index": i}), f"task_execution_failed: {exc!r}", worker_id)
            sink.send(d.topic, d.key, d.value)
            continue
        for e in events:
            emitted += _send_event(sink, e, dirty, counts)
        tasks_done += 1
        if progress is not None and tasks_done % 50 == 0:
            with progress.get_lock():
                progress.value += 50
        if per_worker_rate:
            target = t0 + tasks_done / per_worker_rate
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        now = time.perf_counter()
        if now - last_report >= RESOURCE_INTERVAL_S:
            mem = proc.memory_info().rss / 1e6
            ev = es.WorkerResourceEvent(
                event_id=ids.event_id(rng), event_time=datetime.now(timezone.utc), producer=PRODUCER,
                test_run_id=test_run_id, scenario_id=cfg.name,
                payload=es.WorkerResourcePayload(
                    worker_id=worker_id, cpu_percent=proc.cpu_percent(None), memory_mb=round(mem, 1),
                    tasks_completed=tasks_done, events_emitted=emitted,
                    events_per_sec=round((emitted - last_emitted) / (now - last_report), 1), interval_s=round(now - last_report, 2),
                ),
            )
            emitted += _send_event(sink, ev, None, counts)
            last_report, last_emitted = now, emitted
    if progress is not None:
        with progress.get_lock():
            progress.value += tasks_done % 50
    gen_seconds = time.perf_counter() - t0
    undelivered = sink.flush()
    result_queue.put(
        {
            "worker_id": worker_id,
            "tasks_completed": tasks_done,
            "task_errors": task_errors,
            "events_emitted": emitted,
            "events_by_type": dict(counts),
            "dirty_injected": dict(dirty.injected) if dirty else {},
            "generation_seconds": round(gen_seconds, 3),
            "total_seconds": round(time.perf_counter() - t0, 3),
            "undelivered_after_flush": undelivered,
            "sink": sink.stats(),
        }
    )


# --------------------------------------------------------------------------- orchestration


def machine_info() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_logical": psutil.cpu_count(logical=True),
        "cpu_physical": psutil.cpu_count(logical=False),
        "ram_gb": round(vm.total / 1e9, 1),
        "in_container": os.path.exists("/.dockerenv"),
    }


def run_test(cfg: TestRunConfig, sink_spec: str = "kafka", bootstrap: str | None = None, test_run_id: str | None = None,
             should_stop: Callable[[], bool] | None = None, on_progress: Callable[[int], None] | None = None,
             write_results: bool = True) -> dict[str, Any]:
    bootstrap = bootstrap or get_settings().kafka_bootstrap
    ctx = make_context(cfg, test_run_id)
    cfg = cfg.model_copy(update={"sim_end": ctx.window_end})
    started_at = datetime.now(timezone.utc)
    main_sink = make_sink(sink_spec, bootstrap, client_id=f"{ctx.test_run_id}-main")
    start_ev = test_run_event(ctx, "started", "running", started_at)
    main_sink.send(start_ev.topic.value, start_ev.kafka_key().encode(), start_ev.model_dump_json().encode())
    main_sink.flush(30)

    mpctx = mp.get_context("spawn")
    stop_event = mpctx.Event()
    progress = mpctx.Value("q", 0)
    results = mpctx.Queue()
    t0 = time.perf_counter()
    procs = [
        mpctx.Process(target=worker_main, args=(cfg.model_dump_json(), ctx.test_run_id, w, sink_spec, bootstrap, stop_event, progress, results), daemon=True)
        for w in range(cfg.workers)
    ]
    for p in procs:
        p.start()
    worker_stats: list[dict[str, Any]] = []
    while len(worker_stats) < len(procs):
        if should_stop is not None and should_stop():
            stop_event.set()
        if on_progress is not None:
            on_progress(progress.value)
        try:
            worker_stats.append(results.get(timeout=0.5))
        except Exception:
            if not any(p.is_alive() for p in procs) and results.empty():
                break
    for p in procs:
        p.join(timeout=30)
    wall = time.perf_counter() - t0

    tasks_done = sum(w["tasks_completed"] for w in worker_stats)
    events = sum(w["events_emitted"] for w in worker_stats)
    stopped = stop_event.is_set()
    failed_workers = len(procs) - len(worker_stats)
    status = "failed" if failed_workers else ("stopped" if stopped else "completed")
    end_ev = test_run_event(ctx, "completed", status, started_at, ended_at=datetime.now(timezone.utc),
                            total_runs=tasks_done, total_events=events + 2)
    main_sink.send(end_ev.topic.value, end_ev.kafka_key().encode(), end_ev.model_dump_json().encode())
    main_undelivered = main_sink.flush(30)

    by_type: Counter[str] = Counter()
    dirty: Counter[str] = Counter()
    delivered = failed = undelivered = 0
    for w in worker_stats:
        by_type.update(w["events_by_type"])
        dirty.update(w["dirty_injected"])
        delivered += w["sink"]["delivered"]
        failed += w["sink"]["failed"]
        undelivered += w["undelivered_after_flush"]
    summary = {
        "test_run_id": ctx.test_run_id,
        "scenario": cfg.name,
        "scenario_file": cfg.scenario_file,
        "seed": cfg.seed,
        "status": status,
        "time_mode": cfg.time_mode,
        "sim_window": [ctx.window_start.isoformat(), ctx.window_end.isoformat()] if cfg.time_mode == "simulated" else None,
        "sink": sink_spec,
        "workers": cfg.workers,
        "tasks_requested": cfg.tasks,
        "tasks_completed": tasks_done,
        "task_errors": sum(w["task_errors"] for w in worker_stats),
        "events_emitted": events + 2,
        "events_by_type": dict(by_type),
        "dirty_injected": dict(dirty),
        "delivery": {"delivered": delivered, "failed": failed, "undelivered_after_flush": undelivered + main_undelivered},
        "wall_seconds": round(wall, 3),
        "events_per_sec": round(events / wall, 1) if wall else None,
        "tasks_per_sec": round(tasks_done / wall, 1) if wall else None,
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "machine": machine_info(),
        "workers_detail": worker_stats,
    }
    if write_results:
        out = get_settings().results_dir / f"generator_{ctx.test_run_id}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2))
        summary["results_file"] = str(out)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, help="scenario YAML (generator/scenarios/*.yaml)")
    ap.add_argument("--tasks", type=int)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--time-mode", choices=["simulated", "realtime"])
    ap.add_argument("--sim-days", type=float)
    ap.add_argument("--rate", type=float, dest="rate_per_sec", help="realtime throttle, tasks/s")
    ap.add_argument("--dirty-rate", type=float)
    ap.add_argument("--sink", default="kafka", help="kafka | null | jsonl:<path>")
    ap.add_argument("--bootstrap", default=None)
    ap.add_argument("--test-run-id", default=None)
    args = ap.parse_args(argv)

    cfg = TestRunConfig.from_yaml(
        args.scenario, tasks=args.tasks, workers=args.workers, seed=args.seed, time_mode=args.time_mode,
        sim_days=args.sim_days, rate_per_sec=args.rate_per_sec, dirty_rate=args.dirty_rate,
    )
    last = [0.0]

    def progress(n: int) -> None:
        if time.time() - last[0] > 5:
            last[0] = time.time()
            print(f"  progress: {n}/{cfg.tasks} tasks", flush=True)

    print(f"AgentShield generator: scenario={cfg.name} tasks={cfg.tasks} workers={cfg.workers} sink={args.sink}", flush=True)
    summary = run_test(cfg, args.sink, args.bootstrap, args.test_run_id, on_progress=progress)
    printable = {k: v for k, v in summary.items() if k not in ("workers_detail", "machine")}
    print(json.dumps(printable, indent=2))
    ok = summary["status"] == "completed" and summary["delivery"]["failed"] == 0 and summary["delivery"]["undelivered_after_flush"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
