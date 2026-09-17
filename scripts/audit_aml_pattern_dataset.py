"""Verify every relabeled chain against its immutable source and teaching policy."""

import argparse
from collections import Counter
import csv
from itertools import zip_longest
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.services.aml_pattern_policy import (
    POLICY,
    chain_features,
    label_pattern,
)


def audit(source, dataset):
    output = dataset / "readback-audit.json"
    require(not output.exists(), "Readback receipt already exists")
    receipt = json.loads((dataset / "audit.json").read_bytes())
    require(
        file_hash(source / "audit.json") == receipt["source_audit_sha256"],
        "Wrong source",
    )
    require(
        file_hash(source / "readback-audit.json") == receipt["source_readback_sha256"],
        "Source readback drift",
    )
    source_receipt = json.loads((source / "audit.json").read_bytes())
    for root, data in ((dataset, receipt), (source, source_receipt)):
        for name, expected in data["artifact_hashes"].items():
            require(file_hash(root / name) == expected, "Artifact drift: " + name)

    def read_csv(root, name):
        with (root / name).open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        result = {r["scenario_id"]: r for r in rows}
        require(len(result) == len(rows), "Duplicate ID")
        return result

    features, old_features = (
        read_csv(dataset, "features.csv"),
        read_csv(source, "features.csv"),
    )
    splits, old_splits = read_csv(dataset, "split.csv"), read_csv(source, "split.csv")
    labels, seen, keys = Counter(), set(), {}
    with (
        (dataset / "casebook.jsonl").open(encoding="utf-8") as new,
        (source / "casebook.jsonl").open(encoding="utf-8") as old,
    ):
        for new_line, old_line in zip_longest(new, old):
            require(
                new_line is not None and old_line is not None, "Different corpus length"
            )
            row, original = json.loads(new_line), json.loads(old_line)
            sid = row["scenario_id"]
            require(
                sid == original["scenario_id"] and sid not in seen, "Roster mismatch"
            )
            seen.add(sid)
            require(
                row["public_snapshot"]["steps"] == original["public_snapshot"]["steps"],
                "Changed chain",
            )
            require(
                row["context_sha256"] == original["context_sha256"],
                "Changed common context",
            )
            calculated = chain_features(row["public_snapshot"]["steps"])
            label, patterns = label_pattern(calculated)
            require(
                row["pattern_label"] == int(splits[sid]["pattern_label"]) == label,
                "Label drift",
            )
            require(
                row["matched_patterns"] == patterns
                and row["policy_sha256"] == p.digest(POLICY),
                "Policy drift",
            )
            require(
                all(features[sid][k] == v for k, v in old_features[sid].items()),
                "Base feature changed",
            )
            require(
                all(float(features[sid][k]) == v for k, v in calculated.items()),
                "Chain feature drift",
            )
            require(
                all(
                    splits[sid][k] == old_splits[sid][k] for k in ("group_id", "split")
                ),
                "Changed split",
            )
            key = p.digest(
                {k: v for k, v in features[sid].items() if k != "scenario_id"}
            )
            require(
                keys.setdefault(key, label) == label, "Contradictory observable labels"
            )
            labels[label] += 1
    require(
        seen == set(features) == set(splits) == set(old_features) == set(old_splits),
        "Missing rows",
    )
    report = dict(
        rows=len(seen),
        labels=dict(labels),
        unchanged_chains_and_context=True,
        reused_engine_validation=True,
        all_labels_and_chain_features_recomputed=True,
        contradictory_observable_labels=0,
        split_preserved=True,
        source_audit_sha256=file_hash(dataset / "audit.json"),
        auditor_sha256=file_hash(__file__),
    )
    output.write_bytes(p.json_bytes(report))
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    audit(args.source, args.dataset)
