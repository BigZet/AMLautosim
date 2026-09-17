"""Readback audit of compact paired chain datasets, including exact feature rebuild."""

import argparse
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
import csv
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.audit_aml_history_population import file_hash, require
from scripts.build_aml_chain_dataset import hydrate
from scripts.build_aml_fixed_history_dataset import common_context, private_ledger


def nuisance(steps):
    return sorted(
        p.digest(
            {k: v for k, v in s.items() if k not in ("interval_minutes", "step_id")}
        )
        for s in steps
    )


def validate_chunk(task):
    compact, context = task
    rows = [hydrate(row, context) for row in compact]
    return rows, p.validate_sources(rows, p.protocol())


def validated_rows(path, context):
    # Bound queued work and memory; do not load the JSONL corpus into memory.
    with (
        path.open(encoding="utf-8") as handle,
        ProcessPoolExecutor(max_workers=4) as pool,
    ):
        pending = deque()
        exhausted = False
        while pending or not exhausted:
            while len(pending) < 8 and not exhausted:
                batch = []
                for _ in range(100):
                    line = handle.readline()
                    if not line:
                        exhausted = True
                        break
                    batch.append(json.loads(line))
                if batch:
                    pending.append(pool.submit(validate_chunk, (batch, context)))
            if pending:
                rows, vectors = pending.popleft().result()
                for row in rows:
                    yield row, vectors[row["scenario_id"]]


def audit(directory):
    directory = Path(directory)
    output = directory / "readback-audit.json"
    require(not output.exists(), "Audit receipt already exists")
    receipt = json.loads((directory / "audit.json").read_bytes())
    for name, expected in receipt["artifact_hashes"].items():
        require(file_hash(directory / name) == expected, f"Artifact drift: {name}")
    for name, expected in receipt["source_hashes"].items():
        require(file_hash(name) == expected, f"Source drift: {name}")
    context = json.loads((directory / "context.json").read_bytes())
    require(context == common_context()[0], "Common history/profile drift")
    with (directory / "split.csv").open(encoding="utf-8", newline="") as handle:
        roster = list(csv.DictReader(handle))
    splits = {r["scenario_id"]: r for r in roster}
    require(len(splits) == len(roster), "Duplicate split ID")
    with (directory / "features.csv").open(encoding="utf-8", newline="") as handle:
        stored = list(csv.DictReader(handle))
    features = {r.pop("scenario_id"): r for r in stored}
    require(len(features) == len(stored), "Duplicate feature ID")
    group_splits, root_groups, feature_groups, pending, seen = {}, {}, {}, {}, set()
    classes, families, identical_pairs = Counter(), Counter(), 0
    for row, actual in validated_rows(directory / "casebook.jsonl", context):
        sid = row["scenario_id"]
        require(
            sid not in seen and sid in splits and sid in features, "Roster mismatch"
        )
        seen.add(sid)
        split, group = splits[sid]["split"], splits[sid]["group_id"]
        require(group_splits.setdefault(group, split) == split, "Group leakage")
        root = row["provenance"]["root_id"]
        require(root_groups.setdefault(root, group) == group, "Origin leakage")
        require(int(splits[sid]["aml_label"]) == row["aml_label"], "Label mismatch")
        require(row["review_status"] == "authored_unreviewed", "Unexpected approval")
        ledger = private_ledger(
            row["public_snapshot"]["steps"],
            "criminal_proceeds_concealment"
            if row["aml_label"]
            else "lawful_personal_settlement",
        )
        require(
            all(row["author_truth"].get(key) == value for key, value in ledger.items()),
            "Private principal ledger mismatch",
        )
        for name, value in actual.items():
            expected = features[sid][name]
            require(
                str(value) == expected
                if isinstance(value, str)
                else float(value) == float(expected),
                f"Feature mismatch: {sid}/{name}",
            )
        require(
            feature_groups.setdefault(p.digest(actual), group) == group,
            "Feature leakage",
        )
        pair_id = row["provenance"]["counterfactual_pair_id"]
        other = pending.pop(pair_id, None)
        if other is None:
            pending[pair_id] = row
        else:
            require(other["aml_label"] != row["aml_label"], "Unbalanced pair")
            left, right = (
                other["public_snapshot"]["steps"],
                row["public_snapshot"]["steps"],
            )
            require(
                nuisance(left) == nuisance(right),
                "Class-dependent nuisance sampling",
            )
            identical_pairs += left == right
        classes[row["aml_label"]] += 1
        families[row["chain_family"]] += 1
    require(not pending and seen == set(splits) == set(features), "Missing cases/pairs")
    require(len(seen) == receipt["rows"] and classes[0] == classes[1], "Count mismatch")
    result = dict(
        rows=len(seen),
        classes=dict(classes),
        families=dict(families),
        identical_observation_pairs=identical_pairs,
        recomputed_engine_and_features=True,
        equal_pair_nuisances=True,
        no_group_origin_or_exact_feature_leakage=True,
        context_sha256=p.digest(context),
        release_ready=False,
        source_audit_sha256=file_hash(directory / "audit.json"),
        auditor_sha256=file_hash(__file__),
    )
    output.write_bytes(p.json_bytes(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(audit(parser.parse_args().directory)))
