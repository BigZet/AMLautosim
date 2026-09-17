"""Replay accepted test chains through the released server adapter, without labels."""

import argparse
import csv
import json
from pathlib import Path
from time import monotonic

from src.aml_workshop_simulator.services.game_classifier import (
    get_game_classifier,
    file_hash,
)


def verify(dataset, model, output):
    started = monotonic()
    runtime = get_game_classifier()
    config = {**runtime.context, "risk_model": runtime.identity}
    with (model / "predictions.csv").open(newline="", encoding="utf-8") as stream:
        expected = {
            r["scenario_id"]: float(r["probability"])
            for r in csv.DictReader(stream)
            if r["split"] == "test"
        }
    manifest = json.loads((model / "manifest.json").read_bytes())
    expected_count = manifest["metrics"]["test"]["rows"]
    assert len(expected) == expected_count and expected_count >= 1000, len(expected)
    assert runtime.manifest["model_sha256"] == manifest["model_sha256"]
    assert runtime.manifest["dataset_hashes"] == manifest["dataset_hashes"]
    # Fail immediately if inference accidentally invokes any curriculum labeling rule.
    from src.aml_workshop_simulator.services import aml_game_pattern_panel_v2 as panel
    from src.aml_workshop_simulator.services import aml_game_window_model_v2 as windows

    def forbidden(*args, **kwargs):
        raise AssertionError("Labeling code called during runtime inference")

    panel.assess_panel = forbidden
    windows.interpretation_targets = forbidden
    from scripts import aml_attribute_label_policy
    aml_attribute_label_policy.interpretation_targets = forbidden
    aml_attribute_label_policy.assess_panel = forbidden
    errors, probabilities, seen = [], [], set()
    with (dataset / "casebook.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            key = row["scenario_id"]
            if key not in expected:
                continue
            assert key not in seen, key
            seen.add(key)
            value = runtime.predict(row["steps"], config, explain=False)
            errors.append(abs(value - expected[key]))
            probabilities.append(value)
            if len(seen) % 1000 == 0:
                print(f"Checked {len(seen)}/{expected_count}", flush=True)
    grey = sum(0.1 <= p < 0.9 for p in probabilities) / len(probabilities)
    result = dict(
        passed=seen == expected.keys() and max(errors) <= 1e-10 and 0.1 <= grey <= 0.2,
        chains=len(seen),
        max_absolute_error=max(errors),
        tolerance=1e-10,
        grey_fraction=grey,
        labeling_calls=0,
        model_identity=runtime.identity,
        predictions_sha256=file_hash(model / "predictions.csv"),
        casebook_sha256=file_hash(dataset / "casebook.jsonl"),
        elapsed_seconds=round(monotonic() - started, 2),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    assert result["passed"], result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.dataset, args.model, args.output)
