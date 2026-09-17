"""Fixed-history game curriculum with explicit teaching-interpretation votes.

The curriculum emphasizes resource optimization, with explicit transit and
fragmentation exercises. Sampling never filters individual cases by target.
"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

from scripts.aml_game_curriculum import candidate, catalog
from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import csv_bytes, split_groups
from scripts.audit_aml_history_population import file_hash, require
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from src.aml_workshop_simulator.domain.scoring import (
    resource_score,
    probability_leaderboard_scores,
)
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
    PANEL_POLICY,
    extract_panel_features,
    assess_panel,
)

SEED = 2026100400  # New population, disjoint from all exploratory probes.

CURRICULUM = (
    (0, 15, 20, "existing_transit_routes"),
    (15, 6, 60, "resource_optimization_routes"),
    (21, 1, 3, "seven_payment_boundary"),
    (22, 2, 17, "persistent_eight_payment_fragmentation"),
)


def family_counts(total):
    require(total >= 150, "At least two cases per family required")
    result = {}
    remaining = total
    for index, (start, count, percent, _) in enumerate(CURRICULUM):
        amount = total * percent // 100 if index < len(CURRICULUM) - 1 else remaining
        remaining -= amount
        for offset in range(count):
            result[start + offset] = amount // count + int(offset < amount % count)
    return result


def generate_family(task):
    family, count = task
    config, templates = catalog()
    rows, seen, rejected = [], set(), Counter()
    base = SEED - SEED % len(templates)
    for attempt in range(count * 100):
        seed = base + attempt * len(templates) + family
        actual_config, steps, actual_family, topology = candidate(seed)
        require(
            actual_family == family and actual_config == config, "Family/context drift"
        )
        snapshot = evaluate(steps, config)
        blockers = submit_blockers(snapshot)
        if blockers:
            rejected.update(r["reason"] for r in blockers)
            continue
        key = p.digest([{k: v for k, v in s.items() if k != "step_id"} for s in steps])
        if key in seen:
            rejected["duplicate_observation"] += 1
            continue
        seen.add(key)
        features = extract_panel_features(steps)
        assessment = assess_panel(features)
        resources = resource_score(snapshot, config)
        board = probability_leaderboard_scores(
            assessment["target_probability"], resources, config
        )
        rows.append(
            dict(
                scenario_id=f"game-{family:02d}-{len(rows):05d}",
                seed=seed,
                route_family=templates[family][0],
                family_index=family,
                topology=topology,
                steps=steps,
                features=features,
                **assessment,
                resource_score=float(resources),
                reference_game_score=float(board["game_score"]),
            )
        )
        if len(rows) == count:
            return rows, dict(rejected)
    raise ValueError(
        f"Cannot generate unique valid cases for family {family}: {len(rows)}/{count}"
    )


def build(output, count=30000, workers=4):
    require(not output.exists(), "Output already exists")
    config, templates = catalog()
    counts = family_counts(count)
    sources = {
        *p.compiler_hashes(),
        "scripts/aml_game_curriculum.py",
        __file__,
        "src/aml_workshop_simulator/services/aml_game_pattern_panel.py",
        "src/aml_workshop_simulator/services/aml_game_pattern_panel_v2.py",
        "src/aml_workshop_simulator/domain/scoring.py",
    }
    source_hashes = {name: file_hash(name) for name in sources}
    output.mkdir(parents=True)
    context_hash = p.digest(config)
    (output / "context.json").write_bytes(p.json_bytes(config))
    policy = dict(
        panel=PANEL_POLICY,
        target="observable_educational_pattern",
        sampler=dict(
            seed=SEED,
            family_counts=counts,
            family_names=[name for name, _ in templates],
            curriculum=[dict(start=start, families=n, percent=share, purpose=purpose)
                        for start, n, share, purpose in CURRICULUM],
            design_basis="Content weights selected using exploratory pilot; frozen before final population and model. Not observed player prevalence.",
            selects_by_target_or_predictions=False,
        ),
        interpretation="Positive-vote fraction of synthetic teaching interpretations, not expert consensus or criminal likelihood",
        label_training="Weighted binary classes: positive weight=p, negative weight=1-p; no random label flips",
        grey_acceptance=dict(
            minimum=0.10, maximum=0.20, low_inclusive=0.1, high_exclusive=0.9
        ),
        context_sha256=context_hash,
    )
    (output / "policy.json").write_bytes(p.json_bytes(policy))
    projected_config = deepcopy(config)
    projected_config["behavior"]["history"]["operations"] = []
    closure, feature_rows, targets, vectors, labels = [], [], [], {}, {}
    rejected, bands, rules = Counter(), Counter(), Counter()
    with (
        (output / "casebook.jsonl").open("x", encoding="utf-8") as handle,
        ProcessPoolExecutor(max_workers=workers) as pool,
    ):
        for rows, failures in pool.map(generate_family, counts.items()):
            rejected.update(failures)
            for row in rows:
                sid, features = row["scenario_id"], row.pop("features")
                vectors[sid] = features
                feature_rows.append(dict(scenario_id=sid, **features))
                labels[sid] = dict(aml_label=int(row["target_probability"] >= 0.5))
                closure.append(
                    dict(
                        scenario_id=sid,
                        provenance_group_id=sid,
                        provenance=dict(root_id=sid, parent_ids=[]),
                        public_snapshot=dict(
                            config=projected_config, steps=row["steps"]
                        ),
                    )
                )
                targets.append(
                    {
                        k: row[k]
                        for k in (
                            "scenario_id",
                            "route_family",
                            "positive_votes",
                            "panel_size",
                            "target_probability",
                            "band",
                            "resource_score",
                            "reference_game_score",
                        )
                    }
                )
                bands[row["band"]] += 1
                rules.update(row["rule_support"])
                row["context_sha256"] = context_hash
                handle.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
            print(
                json.dumps(dict(rows=len(targets), family=rows[0]["route_family"])),
                flush=True,
            )
    graph = p.connected_groups(closure, vectors)
    assignment = split_groups(graph["groups"], labels)
    for row in targets:
        row["group_id"] = graph["scenario_groups"][row["scenario_id"]]
        row["split"] = assignment[row["group_id"]]
    (output / "features.csv").write_bytes(
        csv_bytes(list(feature_rows[0]), feature_rows)
    )
    (output / "targets.csv").write_bytes(csv_bytes(list(targets[0]), targets))
    (output / "groups.json").write_bytes(p.json_bytes(graph))
    require(
        all(file_hash(name) == value for name, value in source_hashes.items()),
        "Generation source drift",
    )
    report = dict(
        rows=len(targets),
        bands=dict(bands),
        rejected_reasons=dict(rejected),
        feature_count=len(vectors[next(iter(vectors))]),
        groups=len(graph["groups"]),
        split_counts=dict(Counter(r["split"] for r in targets)),
        rule_positive_votes=dict(rules),
        source_hashes=source_hashes,
        context_sha256=context_hash,
        source_policy_sha256=p.digest(PANEL_POLICY),
        label_consistency="deterministic panel votes; same observable features imply same distribution",
        release_ready=False,
        artifact_hashes={
            name: file_hash(output / name)
            for name in (
                "context.json",
                "policy.json",
                "casebook.jsonl",
                "features.csv",
                "targets.csv",
                "groups.json",
            )
        },
    )
    (output / "audit.json").write_bytes(p.json_bytes(report))
    print(
        json.dumps({k: report[k] for k in ("rows", "bands", "groups", "split_counts")})
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=30000)
    args = parser.parse_args()
    build(args.output, args.count)
