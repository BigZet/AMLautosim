"""Reuse validated chains under the user-approved observable-pattern target."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import csv_bytes, FEATURE_NAMES
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.services.aml_pattern_policy import (
    POLICY,
    chain_features,
    label_pattern,
)


def build(source, output):
    require(not output.exists(), "Output already exists")
    original = json.loads((source / "audit.json").read_bytes())
    for name, expected in original["artifact_hashes"].items():
        require(file_hash(source / name) == expected, "Source artifact drift: " + name)
    with (source / "features.csv").open(encoding="utf-8", newline="") as f:
        base = {r.pop("scenario_id"): r for r in csv.DictReader(f)}
    with (source / "split.csv").open(encoding="utf-8", newline="") as f:
        splits = {r["scenario_id"]: r for r in csv.DictReader(f)}
    output.mkdir(parents=True)
    (output / "context.json").write_bytes((source / "context.json").read_bytes())
    (output / "policy.json").write_bytes(p.json_bytes(POLICY))
    feature_rows, split_rows, labels, patterns, keys = [], [], Counter(), Counter(), {}
    policy_hash = p.digest(POLICY)
    with (
        (source / "casebook.jsonl").open(encoding="utf-8") as f,
        (output / "casebook.jsonl").open("x", encoding="utf-8") as out,
    ):
        for line in f:
            old = json.loads(line)
            sid, steps = old["scenario_id"], old["public_snapshot"]["steps"]
            features = chain_features(steps)
            label, matches = label_pattern(features)
            features = {**base[sid], **features}
            feature_rows.append(dict(scenario_id=sid, **features))
            key = p.digest(features)
            require(
                keys.setdefault(key, label) == label, "Conflicting observable labels"
            )
            labels[label] += 1
            patterns.update(matches)
            split_rows.append(
                dict(
                    scenario_id=sid,
                    group_id=splits[sid]["group_id"],
                    split=splits[sid]["split"],
                    pattern_label=label,
                )
            )
            row = dict(
                scenario_id=sid,
                context_sha256=old["context_sha256"],
                public_snapshot=dict(steps=steps),
                pattern_label=label,
                matched_patterns=matches,
                policy_sha256=policy_hash,
                source_group_id=splits[sid]["group_id"],
            )
            out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    require(
        set(base) == set(splits) and len(feature_rows) == len(base), "Roster mismatch"
    )
    names = [*FEATURE_NAMES, *chain_features([])]
    (output / "features.csv").write_bytes(
        csv_bytes(["scenario_id", *names], feature_rows)
    )
    (output / "split.csv").write_bytes(
        csv_bytes(["scenario_id", "group_id", "split", "pattern_label"], split_rows)
    )
    report = dict(
        rows=len(feature_rows),
        labels=dict(labels),
        patterns=dict(patterns),
        feature_count=len(names),
        contradictory_feature_labels=0,
        target=POLICY["target"],
        inherited_group_split=True,
        source_audit_sha256=file_hash(source / "audit.json"),
        source_readback_sha256=file_hash(source / "readback-audit.json"),
        policy_source_sha256=file_hash(
            "src/aml_workshop_simulator/services/aml_pattern_policy.py"
        ),
        source_sha256=file_hash(__file__),
        release_ready=False,
        label_basis="user-approved change of target; deterministic educational patterns, not criminal truth",
        artifact_hashes={
            name: file_hash(output / name)
            for name in (
                "casebook.jsonl",
                "context.json",
                "policy.json",
                "features.csv",
                "split.csv",
            )
        },
    )
    (output / "audit.json").write_bytes(p.json_bytes(report))
    print(
        json.dumps(
            {k: report[k] for k in ("rows", "labels", "patterns", "feature_count")}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.output)
