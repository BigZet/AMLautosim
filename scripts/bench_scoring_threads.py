"""Bounded current-model thread experiment; each thread owns its scorer."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
from threading import Barrier, local
import time
from types import SimpleNamespace

import psutil

from src.aml_workshop_simulator.services.game_classifier import (
    GameClassifier,
    DEFAULT_PACKAGE,
)
from src.aml_workshop_simulator.services.scenario_service import (
    load_round_card_specs,
    round_policy,
)
from src.aml_workshop_simulator.services.scoring_service import _evaluate


def benchmark(count=60, repeats=3):
    fixture = Path("tests/fixtures/runtime_compatibility_baseline.json")
    baseline = json.loads(fixture.read_bytes())
    config = baseline["config"]
    steps = [baseline["rows"][i % len(baseline["rows"])]["steps"] for i in range(count)]
    specs = load_round_card_specs(SimpleNamespace(game_config=config))
    policy = round_policy(SimpleNamespace(game_config=config), specs)
    process = psutil.Process()
    expected = None
    runs = []
    for workers in (1, 2, 4):
        thread = local()
        barrier = Barrier(workers)

        def initialize():
            thread.scorer = GameClassifier(DEFAULT_PACKAGE)
            thread.scorer.check_config(config, require_pin=True)

        def calculate(value):
            # No ORM object or session is passed into the executor.
            result = _evaluate(deepcopy(value), specs, config, policy, thread.scorer)
            return hashlib.sha256(
                json.dumps(result, sort_keys=True, default=str).encode()
            ).hexdigest()

        def warm():
            barrier.wait(timeout=60)
            return calculate(steps[0])

        started = time.perf_counter()
        with ThreadPoolExecutor(workers, initializer=initialize) as pool:
            warming = [pool.submit(warm) for _ in range(workers)]
            for future in warming:
                future.result(timeout=60)
            startup = time.perf_counter() - started
            timings = []
            cpu = sum(process.cpu_times()[:2])
            for _ in range(repeats):
                started = time.perf_counter()
                hashes = []
                for offset in range(0, count, workers):
                    batch = [
                        pool.submit(calculate, value)
                        for value in steps[offset : offset + workers]
                    ]
                    hashes.extend(future.result(timeout=60) for future in batch)
                timings.append(time.perf_counter() - started)
                if expected is None:
                    expected = hashes
                if hashes != expected:
                    raise ValueError("parallel_scoring_changed_results")
            runs.append(
                {
                    "workers": workers,
                    "startup_seconds": startup,
                    "seconds": timings,
                    "cpu_seconds": sum(process.cpu_times()[:2]) - cpu,
                    "rss_after_bytes": process.memory_info().rss,
                    "outputs_identical": True,
                }
            )
    return {
        "count": count,
        "repeats": repeats,
        "catboost_thread_count": 1,
        "platform": platform.platform(),
        "cpu_count": psutil.cpu_count(),
        "ram_bytes": psutil.virtual_memory().total,
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "package_sha256": GameClassifier(DEFAULT_PACKAGE).package_sha256,
        "runs": runs,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.count <= 300 or not 1 <= args.repeats <= 10:
        parser.error("count must be1..300 and repeats1..10")
    result = benchmark(args.count, args.repeats)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
