"""Rebind the unchanged classifier for organizer-owned draft settings."""

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
from scripts.package_retired_limits import SOURCES
from src.aml_workshop_simulator.services.source_hashing import source_sha256


def _build(source, baseline_path, output):
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    release = json.loads((source / "release.json").read_bytes())
    require(
        digest(release) == baseline["identity"]["package_sha256"],
        "Package verification failed: digest(release) == baseline['identity']['package_sha256']",
    )
    for name, expected in release["files"].items():
        require(
            file_hash(source / name) == expected,
            "Package verification failed: file_hash(source / name) == expected",
        )
    require(
        len(baseline["rows"]) >= 25,
        "Package verification failed: len(baseline['rows']) >= 25",
    )
    previous_pins = []
    if output.exists():
        previous = json.loads((output / "release.json").read_bytes())
        require(
            previous.get("organizer_settings_version") == 1,
            "Package verification failed: previous.get('organizer_settings_version') == 1",
        )
        require(
            previous["files"] == release["files"],
            "Package verification failed: previous['files'] == release['files']",
        )
        for name, expected in release["files"].items():
            require(
                file_hash(output / name) == expected,
                "Package verification failed: file_hash(output / name) == expected",
            )
        previous_pins = [
            dict(
                baseline["identity"],
                package_sha256=digest(previous),
                model_version="aml-game:sha256:" + digest(previous),
            ),
            *previous.get("compatible_identities", []),
        ]
    else:
        shutil.copytree(source, output)
    release["organizer_settings_version"] = 1
    release["source_hash_mode"] = "lf-v1"
    release["inference_sources"] = {
        name: source_sha256(ROOT / name) for name in release["inference_sources"]
    }
    sources = (
        *SOURCES,
        "src/aml_workshop_simulator/schemas/expanded_contract.py",
        "src/aml_workshop_simulator/services/counterparties.py",
        "src/aml_workshop_simulator/services/aml_context.py",
        "src/aml_workshop_simulator/services/semantic_contract.py",
    )
    release["compatibility_sources"] = {
        name: source_sha256(ROOT / name) for name in sources
    }
    release["compatible_identities"] = [
        baseline["identity"],
        *release.get("compatible_identities", []),
        *previous_pins,
    ]
    release["compatible_identities"] = list({
        digest(pin): pin for pin in release["compatible_identities"]
    }.values())
    release["compatibility"] = dict(
        version="organizer-settings-v1",
        source_package_sha256=digest(
            json.loads((source / "release.json").read_bytes())
        ),
        baseline_sha256=file_hash(baseline_path),
        compared_chains=len(baseline["rows"]),
        features_equal=True,
        probabilities_equal=True,
    )
    (output / "release.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    model = GameClassifier(output)
    for row in baseline["rows"]:
        require(
            model.extract(row["steps"]) == row["features"],
            "Package verification failed: model.extract(row['steps']) == row['features']",
        )
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

    with staged_package(output, refresh=True) as staged:
        _build(source, baseline_path, staged)
    count = len(json.loads(baseline_path.read_text(encoding="utf-8"))["rows"])
    print(
        f"Verified {count} identical feature vectors and predictions; model artifacts unchanged"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "baseline", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    package(args.source, args.baseline, args.output)
