"""Read-only model verification; writes a report to an explicit new output file."""

import argparse
import csv
import json
import time
from pathlib import Path
from src.aml_workshop_simulator.services.model_scoring import get_model_scorer


def verify(dataset, predictions, output):
    if output.exists():
        raise ValueError("Output must be new")
    scorer = get_model_scorer()
    expected = {
        r["id"]: r for r in csv.DictReader(predictions.open()) if r["split"] == "test"
    }
    count = 0
    delta = 0.0
    residual = 0.0
    durations = []
    started = time.perf_counter()
    with (dataset / "scenarios.jsonl").open() as source:
        for line in source:
            row = json.loads(line)
            if row["split"] != "test":
                continue
            config = row["config_snapshot"]
            config["risk_model"] = scorer.identity.copy()
            before = time.perf_counter()
            result = scorer.score(row["steps"], config)
            durations.append(time.perf_counter() - before)
            e = result["explanation"]
            reference = expected.pop(row["id"])
            delta = max(delta, abs(e["raw_score"] - float(reference["prediction_raw"])))
            residual = max(residual, e["additivity_error"])
            count += 1
            if count % 250 == 0:
                print("verified", count, flush=True)
    assert count == 4413 and not expected and delta <= 1e-8 and residual <= 1e-6
    # First 100 actual serial explanations, four native CPU threads.
    report = dict(
        passed=True,
        rows=count,
        max_prediction_error=delta,
        max_shap_additivity_error=residual,
        seconds=time.perf_counter() - started,
        first_100_seconds=sum(durations[:100]),
        p95_seconds=sorted(durations)[int(0.95 * len(durations))],
        model=scorer.identity,
    )
    assert report["first_100_seconds"] <= 60
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(report)


if __name__ == "__main__":
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    verify(args.dataset, args.predictions, args.output)
