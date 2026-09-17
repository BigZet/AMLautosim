"""Read-only model verification; writes a report to an explicit new output file."""

import argparse
import csv
import json
import math
import time
from pathlib import Path
from src.aml_workshop_simulator.services.model_scoring import get_model_scorer


def verify(dataset, predictions, output):
    if output.exists():
        raise ValueError("Output must be new")
    scorer = get_model_scorer()
    expected = {}
    with predictions.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if row["split"] != "test":
                continue
            row_id = row["id"]
            if not row_id or not row_id.strip() or row_id in expected:
                raise ValueError(f"Missing or duplicate prediction test ID: {row_id!r}")
            prediction = float(row["prediction_raw"])
            if not math.isfinite(prediction):
                raise ValueError(f"Prediction must be finite for test ID {row_id!r}")
            expected[row_id] = prediction
    count = 0
    delta = 0.0
    residual = 0.0
    durations = []
    started = time.perf_counter()
    with (dataset / "scenarios.jsonl").open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if row["split"] != "test":
                continue
            row_id = row["id"]
            if row_id not in expected:
                raise ValueError(f"Unknown or duplicate scenario test ID: {row_id!r}")
            reference = expected.pop(row_id)
            config = row["config_snapshot"]
            config["risk_model"] = scorer.identity.copy()
            before = time.perf_counter()
            result = scorer.score(row["steps"], config)
            durations.append(time.perf_counter() - before)
            e = result["explanation"]
            if not math.isfinite(e["raw_score"]) or not math.isfinite(e["additivity_error"]):
                raise ValueError(f"Prediction and SHAP error must be finite for test ID {row_id!r}")
            delta = max(delta, abs(e["raw_score"] - reference))
            residual = max(residual, abs(e["additivity_error"]))
            count += 1
            if count % 250 == 0:
                print("verified", count, flush=True)
    if count != 4413:
        raise ValueError(f"Expected 4413 test rows, verified {count}")
    if expected:
        raise ValueError(f"Missing scenarios for {len(expected)} prediction test IDs")
    if delta > 1e-8:
        raise ValueError(f"Prediction error exceeds 1e-8: {delta}")
    if residual > 1e-6:
        raise ValueError(f"SHAP additivity error exceeds 1e-6: {residual}")
    # First 100 actual serial explanations, four native CPU threads.
    first_100_seconds = sum(durations[:100])
    if first_100_seconds > 60:
        raise ValueError(f"First 100 explanations exceed 60 seconds: {first_100_seconds}")
    report = dict(
        passed=True,
        rows=count,
        max_prediction_error=delta,
        max_shap_additivity_error=residual,
        seconds=time.perf_counter() - started,
        first_100_seconds=first_100_seconds,
        p95_seconds=sorted(durations)[int(0.95 * len(durations))],
        model=scorer.identity,
    )
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        target.write(serialized)
    print(report)


if __name__ == "__main__":
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    verify(args.dataset, args.predictions, args.output)
