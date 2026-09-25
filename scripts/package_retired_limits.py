"""Rebind unchanged classifier artifacts after retiring gameplay limits.

The baseline must be captured with the prior runtime before editing its rules.
Archived training and acceptance artifacts are copied byte-for-byte.
"""

from scripts.package_verification import require
import argparse
import json
import shutil
from pathlib import Path
from src.aml_workshop_simulator.services.game_classifier import (
    ROOT,
    GameClassifier,
    digest,
    file_hash,
)
from src.aml_workshop_simulator.services.source_hashing import source_sha256

SOURCES = (
    "src/aml_workshop_simulator/services/game_classifier.py",
    "src/aml_workshop_simulator/schemas/round_config.py",
    "src/aml_workshop_simulator/domain/game_models.py",
    "src/aml_workshop_simulator/domain/simulation.py",
    "config/base_round.json",
    "src/aml_workshop_simulator/services/source_hashing.py",
)


def _build(source, baseline_path, output):
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    original = GameClassifier(source)
    require(
        baseline["identity"]["package_sha256"] == digest(original.release),
        "Package verification failed: baseline['identity']['package_sha256'] == digest(original.release)",
    )
    require(
        baseline["identity"]["model_sha256"] == original.identity["model_sha256"],
        "Package verification failed: baseline['identity']['model_sha256'] == original.identity['model_sha256']",
    )
    require(
        len(baseline["rows"]) >= 25,
        "Package verification failed: len(baseline['rows']) >= 25",
    )
    for row in baseline["rows"]:
        require(
            original.extract(row["steps"]) == row["features"],
            "Package verification failed: original.extract(row['steps']) == row['features']",
        )
        require(
            original.predict(
                row["steps"], original.context, require_pin=False, explain=False
            )
            == row["probability"],
            "Package verification failed: original.predict(row['steps'], original.context, require_pin=False, explain=False) == row['probability']",
        )
    if output.exists():
        raise FileExistsError(output)
    shutil.copytree(source, output)
    release = json.loads((output / "release.json").read_bytes())
    release["source_hash_mode"] = "lf-v1"
    release["inference_sources"] = {
        name: source_sha256(ROOT / name) for name in release["inference_sources"]
    }
    release["compatibility_sources"] = {
        name: source_sha256(ROOT / name) for name in SOURCES
    }
    release["compatible_identities"] = [baseline["identity"]]
    release["compatibility"] = {
        "version": "retired-night-anonymous-limits-v1",
        "baseline_sha256": file_hash(baseline_path),
        "compared_chains": len(baseline["rows"]),
        "features_equal": True,
        "probabilities_equal": True,
        "source_package_sha256": digest(original.release),
    }
    (output / "release.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    model = GameClassifier(output)
    for row in baseline["rows"]:
        require(
            model.predict(
                row["steps"],
                {**model.context, "risk_model": baseline["identity"]},
                explain=False,
            )
            == row["probability"],
            "Package verification failed: model.predict(row['steps'], {**model.context, 'risk_model': baseline['identity']}, explain=False) == row['probability']",
        )


def package(source, baseline_path, output):
    from scripts.package_verification import staged_package

    with staged_package(output) as staged:
        _build(source, baseline_path, staged)
    count = len(json.loads(baseline_path.read_text(encoding="utf-8"))["rows"])
    print(
        f"Verified {count} identical feature vectors and predictions; model artifacts unchanged"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package(args.source, args.baseline, args.output)
