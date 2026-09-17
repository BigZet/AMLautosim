"""Stream saved fixed-context records and verify checksums, labels and split isolation."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from scripts.audit_aml_history_population import file_hash, require
from scripts.aml_dataset.aml_labels import validate_label, validate_public
from scripts.aml_dataset import aml_population_author as p
from scripts.build_aml_fixed_history_dataset import common_context, private_ledger


def audit(directory):
    directory = Path(directory)
    receipt = json.loads((directory / "audit.json").read_bytes())
    for name, expected in receipt["artifact_hashes"].items():
        require(
            file_hash(directory / name) == expected,
            "Artifact checksum mismatch: " + name,
        )
    for name, expected in receipt["source_hashes"].items():
        require(file_hash(name) == expected, "Generation source drift: " + name)
    context, _ = common_context()
    expected_context = p.digest(context)
    require(
        json.loads((directory / "context.json").read_bytes()) == context,
        "Canonical context mismatch",
    )
    with (directory / "split.csv").open(newline="", encoding="utf-8") as handle:
        split_rows = list(csv.DictReader(handle))
    splits = {r["scenario_id"]: r for r in split_rows}
    require(len(splits) == len(split_rows), "Duplicate split row")
    group_splits, feature_groups, feature_ids, seen, labels = (
        {},
        {},
        set(),
        set(),
        Counter(),
    )
    for row in split_rows:
        old = group_splits.setdefault(row["group_id"], row["split"])
        require(old == row["split"], "Connected group crosses splits")
    with (directory / "features.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sid = row.pop("scenario_id")
            require(sid not in feature_ids and sid in splits, "Feature roster mismatch")
            feature_ids.add(sid)
            key = p.digest(row)
            group = splits[sid]["group_id"]
            require(
                feature_groups.setdefault(key, group) == group,
                "Equal features cross groups",
            )
    with (directory / "casebook.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            sid = row["scenario_id"]
            require(sid not in seen and sid in splits, "Casebook roster mismatch")
            seen.add(sid)
            validate_label(row)
            validate_public(row["public_snapshot"])
            require(
                p.digest(row["public_snapshot"]["config"]) == expected_context,
                "History/profile/context changed",
            )
            require(
                row["review_status"] == "authored_unreviewed",
                "Unexpected automatic review approval",
            )
            require(
                str(row["aml_label"]) == splits[sid]["aml_label"],
                "CSV/JSON label mismatch",
            )
            truth = private_ledger(
                row["public_snapshot"]["steps"], row["author_truth"]["episode"]
            )
            require(
                truth["aml_episode_present"] is bool(row["aml_label"]),
                "Private outcome mismatch",
            )
            require(
                truth["actual_payments"] == row["author_truth"]["actual_payments"],
                "Private flow mismatch",
            )
            labels[row["aml_label"]] += 1
    require(
        seen == set(splits) == feature_ids and len(seen) == receipt["rows"],
        "Export row count mismatch",
    )
    require(labels[0] == labels[1], "Class balance mismatch")
    result = dict(
        rows=len(seen),
        labels=dict(labels),
        fixed_context_sha256=expected_context,
        profile=context["behavior"]["profile"]["id"],
        history_operations=len(context["behavior"]["history"]["operations"]),
        conditional_groups=len(group_splits),
        split_counts=dict(Counter(r["split"] for r in split_rows)),
        all_artifact_hashes_verified=True,
        source_hashes_verified=True,
        identical_full_context=True,
        no_group_or_feature_leakage=True,
        source_audit_sha256=file_hash(directory / "audit.json"),
        validator_sha256=file_hash(__file__),
        engine_validation="All rows passed actual engine during source-bound generation",
        independent_domain_review=False,
        release_ready=False,
    )
    target = directory / "readback-audit.json"
    require(not target.exists(), "Readback receipt already exists")
    target.write_bytes(p.json_bytes(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.dataset)))
