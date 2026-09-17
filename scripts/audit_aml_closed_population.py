"""Measure selected draft data against all retained observations, without review."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.audit_aml_history_population import check_economics, file_hash, require


def audit(population, universe, output):
    population, universe, output = Path(population), Path(universe), Path(output)
    require(not output.exists(), "Audit output already exists")
    receipt = json.loads((population / "audit.json").read_bytes())
    whole = json.loads((universe / "audit.json").read_bytes())
    for name, expected in receipt["artifact_hashes"].items():
        require(
            file_hash(population / name) == expected, "Population artifact mismatch"
        )
    require(
        file_hash(universe / "provenance.json") == whole["provenance_sha256"],
        "Universe graph checksum mismatch",
    )
    require(
        whole["input_hashes"][str(population / "audit.json")]
        == file_hash(population / "audit.json"),
        "Population is not bound to universe",
    )
    graph = json.loads((universe / "provenance.json").read_bytes())
    vectors = json.loads((population / "features.json").read_bytes())
    labels, groups, profiles, channels, conflicts = (
        Counter(),
        Counter(),
        defaultdict(lambda: defaultdict(set)),
        defaultdict(lambda: defaultdict(set)),
        defaultdict(Counter),
    )
    seen, reviews, opaque = set(), Counter(), 0
    for line in (population / "main.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        sid, label = row["scenario_id"], row["aml_label"]
        require(sid not in seen, "Repeated main scenario")
        seen.add(sid)
        check_economics(row)
        gid = graph["scenario_groups"]["main:" + sid]
        labels[label] += 1
        groups[gid] += 1
        reviews[row["review_status"]] += 1
        opaque += "opaque" in row["variant_recipe"]
        profiles[row["public_snapshot"]["config"]["behavior"]["profile"]["id"]][
            label
        ].add(gid)
        for channel in {
            s.get("action_details", {}).get("incoming_kind", s["card"]["code"])
            for s in row["public_snapshot"]["steps"]
        }:
            channels[channel][label].add(gid)
        conflicts[p.digest(vectors[sid])][label] += 1
    mixed = [counts for counts in conflicts.values() if counts[0] and counts[1]]
    crossings = [
        gid
        for gid in groups
        if any(
            s.startswith(
                ("demo:", "development:", "coverage-v1:", "coverage-v2:", "challenges:")
            )
            for s in graph["groups"][gid]
        )
    ]
    checks = dict(
        minimum_30000_rows=len(seen) >= 30000,
        minimum_1200_closed_main_groups=len(groups) >= 1200,
        uniform_25_variants=set(groups.values()) == {25},
        balanced_classes=labels[0] == labels[1],
        no_reserved_component_crossings=not crossings,
        no_demo_crossings=not whole["demo_crossings"],
        all_profiles_both_classes=all(set(c) == {0, 1} for c in profiles.values()),
        all_observed_channels_both_classes=all(
            set(c) == {0, 1} for c in channels.values()
        ),
    )
    report = dict(
        scope="selected-draft-main-after-complete-retained-universe-closure",
        main_rows=len(seen),
        class_counts=dict(labels),
        closed_main_groups=len(groups),
        component_size_distribution=dict(Counter(groups.values())),
        opaque_rows=opaque,
        review_counts=dict(reviews),
        profile_class_groups={
            key: {str(label): len(gids) for label, gids in cells.items()}
            for key, cells in profiles.items()
        },
        channel_class_groups={
            key: {str(label): len(gids) for label, gids in cells.items()}
            for key, cells in channels.items()
        },
        conflicting_feature_vectors=len(mixed),
        conflicting_feature_rows=sum(sum(c.values()) for c in mixed),
        empirical_feature_collision_error_floor=sum(min(c[0], c[1]) for c in mixed)
        / len(seen),
        checks=checks,
        generation_and_structural_checks_passed=all(checks.values()),
        population_receipt_sha256=file_hash(population / "audit.json"),
        universe_receipt_sha256=file_hash(universe / "audit.json"),
        auditor_sha256=file_hash(__file__),
        release_ready=False,
        remaining=[
            "independent exact-record domain review",
            "materialize reviewed training dataset after domain review",
            "audit final train/validation/calibration/test subgroup support",
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(p.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("population", "universe", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.population, args.universe, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "main_rows",
                    "closed_main_groups",
                    "checks",
                    "conflicting_feature_rows",
                    "release_ready",
                )
            }
        )
    )
