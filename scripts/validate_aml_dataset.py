"""Validate exported dataset against its frozen game contract and independent rubric."""

import argparse
import csv
import hashlib
import math
import json
from collections import Counter
from pathlib import Path

from scripts.aml_dataset.core import (
    content_hash,
    digest,
    label,
    read_json,
    read_jsonl,
)
from src.aml_workshop_simulator.domain.rules import evaluate_scenario, submit_blockers
from src.aml_workshop_simulator.services.aml_dataset_features import extract_features
from src.aml_workshop_simulator.services.configuration import snapshot_specs


def read_csv(path):
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def check(condition, message):
    if not condition:
        raise ValueError(message)


def validate(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    config = read_json(directory / "round_config.json")
    rubric = read_json(directory / "rubric.json")
    rows = read_jsonl(directory / "scenarios.jsonl")
    check(bool(rows), "Empty dataset")
    check(digest(config) == manifest["config_hash"], "Configuration hash mismatch")
    check(digest(rubric) == manifest["rubric_hash"], "Rubric hash mismatch")
    check(digest(rows) == manifest["records_hash"], "Records hash mismatch")
    check(len(rows) == manifest["rows"], "Record count mismatch")
    for name, expected in manifest["artifact_hashes"].items():
        check(
            hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected,
            f"Artifact changed: {name}",
        )
    features_csv = read_csv(directory / "features.csv")
    labels_csv = read_csv(directory / "labels.csv")
    splits = read_csv(directory / "splits.csv")
    check(
        len(features_csv) == len(rows) == len(labels_csv) == len(splits),
        "CSV row count mismatch",
    )
    feature_rows = {r["scenario_id"]: r for r in features_csv}
    label_rows = {r["scenario_id"]: r for r in labels_csv}
    split_rows = {r["scenario_id"]: r for r in splits}
    ids = {r["scenario_id"] for r in rows}
    check(len(ids) == len(rows), "Duplicate scenario")
    check(
        ids == feature_rows.keys() == label_rows.keys() == split_rows.keys(),
        "CSV IDs mismatch",
    )
    check(
        set(features_csv[0]) == {"scenario_id", *manifest["features"]},
        "Unlisted feature column",
    )
    by_feature, groups, templates = {}, {}, {}
    specs = snapshot_specs(config)
    for row in rows:
        sid = row["scenario_id"]
        check(content_hash(row["steps"]) == sid, "Content identity mismatch")
        check(row["config_hash"] == digest(config), "Record config mismatch")
        check(
            not submit_blockers(evaluate_scenario(row["steps"], specs, config)),
            f"Cannot submit {sid}",
        )
        features = extract_features(row["steps"], config)
        check(features == row["features"], f"Extractor mismatch {sid}")
        score, reasons = label(features, rubric)
        check(
            score == row["target_risk_score"] and reasons == row["reasons"],
            f"Label mismatch {sid}",
        )
        check(0 <= score <= 100 and math.isfinite(score), "Invalid target")
        check(
            float(label_rows[sid]["target_risk_score"]) == score, "CSV label mismatch"
        )
        for key in manifest["features"]:
            value = features[key]
            if isinstance(value, (float, int)):
                check(
                    math.isfinite(value) and float(feature_rows[sid][key]) == value,
                    f"Invalid numeric {key}",
                )
            else:
                check(
                    isinstance(value, str) and value == feature_rows[sid][key],
                    f"Invalid category {key}",
                )
        split = split_rows[sid]
        check(split["split"] in {"train", "validation", "test"}, "Unknown split")
        for lookup, key in [
            (templates, row["template_id"]),
            (groups, split["group_id"]),
        ]:
            check(
                lookup.setdefault(key, split["split"]) == split["split"],
                "Related template split leakage",
            )
        fh = digest({k: features[k] for k in manifest["features"]})
        check(
            by_feature.setdefault(fh, (score, split["split"]))
            == (score, split["split"]),
            "Feature conflict or leakage",
        )
    check(
        {s["split"] for s in splits} == {"train", "validation", "test"}, "Empty split"
    )
    actual_constants = {
        k for k in rows[0]["features"] if len({r["features"][k] for r in rows}) == 1
    }
    check(
        actual_constants == set(manifest["excluded_constant_features"]),
        "Constant feature manifest mismatch",
    )
    check(
        not actual_constants.intersection(manifest["features"]), "Constant feature in X"
    )
    for row in read_jsonl(directory / "diagnostics.jsonl"):
        check(
            bool(submit_blockers(evaluate_scenario(row["steps"], specs, config))),
            "Valid row incorrectly classified as diagnostic",
        )
    if manifest["stage"] == "review":
        check(
            len(rows) == 48 and set(Counter(r["family"] for r in rows).values()) == {8},
            "Expected 8 references per family",
        )
        challenge = read_jsonl(directory / "challenge_blind.jsonl")
        challenge_ids = {r["scenario_id"] for r in challenge}
        check(
            len(challenge_ids) == 24 and not ids.intersection(challenge_ids),
            "Challenge duplicates",
        )
        for row in challenge:
            check(
                "target_risk_score" not in row,
                "Challenge labels must be independently reviewed",
            )
            check(
                content_hash(row["steps"]) == row["scenario_id"],
                "Challenge content mismatch",
            )
            check(
                not submit_blockers(evaluate_scenario(row["steps"], specs, config)),
                "Invalid challenge",
            )
        for pair in read_jsonl(directory / "counterfactual_pairs.jsonl"):
            after, _ = label(extract_features(pair["variant"]["steps"], config), rubric)
            check(after == pair["after"], "Counterfactual score mismatch")
            if pair["expected"] == "equal":
                check(after == pair["before"], "Neutral mutation changes risk")
            elif pair["expected"] == "not_lower":
                check(after >= pair["before"], "Rapid mutation lowers risk")
    return {
        "rows": len(rows),
        "features": len(manifest["features"]),
        "stage": manifest["stage"],
        "status": "valid; human review status is separate",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.dataset:
            from scripts.aml_dataset.aml_training import audit_dataset

            if args.directory or not args.output:
                parser.error("--dataset requires --output and no positional directory")
            if args.output.exists():
                raise FileExistsError(f"Refusing existing output: {args.output}")
            if args.output.resolve().is_relative_to(args.dataset.resolve()):
                raise ValueError("Audit report must be outside the immutable dataset")
            report = audit_dataset(args.dataset)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(report)
        elif args.directory and not args.output:
            print(validate(args.directory))
        else:
            parser.error("Supply directory or --dataset DATASET --output REPORT")
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
