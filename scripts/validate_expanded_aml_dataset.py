"""Validate saved review material, including CSV, partitions and snapshot hashes."""

import argparse
import csv
import json
from pathlib import Path
from scripts.aml_dataset.expanded import validate, digest, rubric
from src.aml_workshop_simulator.services.aml_dataset_features_v2 import FEATURE_VERSION


def validate_directory(path):
    def read(name):
        return json.loads((path / name).read_text())

    package = {"config": read("config.json")}
    for key in ("references", "challenges", "pairs", "diagnostics"):
        package[key] = [
            json.loads(line)
            for line in (path / f"{key}.jsonl").read_text().splitlines()
        ]
    manifest = read("manifest.json")
    package["seed"] = manifest["seed"]
    assert manifest["package_hash"] == digest(package)
    assert (
        manifest["status"] == "pending_joint_review"
        and not manifest["mass_generation_enabled"]
    )
    assert manifest["extractor"] == FEATURE_VERSION
    assert manifest["config_hash"] == digest(package["config"])
    assert manifest["rubric_hash"] == digest(read("rubric.json")) == digest(rubric())
    report = validate(package)
    assert read("quality.json") == report
    schema = read("feature-schema.json")
    expected_columns = [
        k
        for k in package["references"][0]["features"]
        if k not in report["constant_features"]
    ]
    # JSONL keys are sorted; schema order follows extractor, not JSON serialization.
    assert set(schema["columns"]) == set(expected_columns)
    assert schema["excluded_constants"] == report["constant_features"] or set(
        schema["excluded_constants"]
    ) == set(report["constant_features"])
    with (path / "features.csv").open() as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames == schema["columns"] + ["target_risk_score"]
        rows = list(reader)
    assert len(rows) == 48
    with (path / "split.csv").open() as file:
        split = list(csv.DictReader(file))
    assert len(split) == 48
    groups = {}
    for i, (row, partition, reference) in enumerate(
        zip(rows, split, package["references"])
    ):
        assert (
            partition["row_index"] == str(i)
            and partition["id"] == reference["id"]
            and partition["group"] == reference["group"]
        )
        assert (
            partition["split"]
            == {
                "five-transfers": "train",
                "six-transfers": "validation",
                "eight-transfers": "test",
            }[reference["group"]]
        )
        assert (
            groups.setdefault(partition["group"], partition["split"])
            == partition["split"]
        )
        for key in schema["columns"]:
            assert row[key] == str(reference["features"][key])
        assert float(row["target_risk_score"]) == reference["target_risk_score"]
    return report


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.directory / "manifest.json").read_text())
    if manifest.get("stage") in ("pilot", "release"):
        from scripts.aml_dataset.mass_release import validate_mass

        print(validate_mass(args.directory))
    else:
        print(validate_directory(args.directory))


if __name__ == "__main__":
    main()
