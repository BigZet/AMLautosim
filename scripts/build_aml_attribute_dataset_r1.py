"""Fixed-history game curriculum with explicit teaching-interpretation votes.

The curriculum emphasizes resource optimization, with explicit transit and
fragmentation exercises. This version explicitly samples teaching difficulty strata by fixed-policy target, never model predictions.
"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

from scripts.aml_game_curriculum_v9 import catalog
from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import csv_bytes, split_groups
from scripts.audit_aml_history_population import file_hash, require
from scripts.aml_attribute_supplement import generate_family, BASE
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
    PANEL_POLICY,
)

SEED = 2051900000


def family_counts(total):
    require(total >= 150, 'Insufficient curriculum size')
    low = int(total * .425)
    totals = dict(low=low, high=low, grey=total - 2 * low)
    return {f'{band}:{start // 60000}': min(60000, count-start)
            for band, count in totals.items() for start in range(0,count,60000)}


def build(output, count=60000, workers=4):
    require(not output.exists(), "Output already exists")
    config, templates = catalog()
    counts = family_counts(count)
    sources = {
        *p.compiler_hashes(),
        'scripts/aml_game_curriculum_v3.py',
        'scripts/aml_game_curriculum_v4.py',
        'scripts/aml_game_curriculum_v5.py',
        'scripts/aml_game_curriculum_v7.py',
        'scripts/aml_game_curriculum_v8.py',
        'scripts/aml_game_curriculum_v9.py',
        'scripts/aml_attribute_supplement.py',
        'scripts/build_aml_game_dataset_v9.py',
        'src/aml_workshop_simulator/services/semantic_contract.py',
        'config/game_curriculum_defaults_v4.json',
        'config/game_curriculum_defaults_v3.json',
        'src/aml_workshop_simulator/domain/operation_purposes.py',
        'config/base_round.json',
        'config/game_curriculum_defaults_v1.json',
        'src/aml_workshop_simulator/core/game_config.py',
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
        base_artifact_hashes=json.loads((BASE / "audit.json").read_bytes())["artifact_hashes"],
        salary_supplement=dict(rows=2000,seed=2081900000,related_variants_kept_with_parent=True),
        sampler=dict(
            seed=SEED,
            batch_counts=counts, requested_band_shares=dict(low=.425, high=.425, grey=.15),
            family_names=[name for name, _ in templates],
            design_basis="Explicit authored teaching strata fixed before training: 42.5% low, 42.5% high, 15% ambiguous. Target-based scenario sampling, not observed player prevalence; target probabilities remain unchanged.",
            selects_by_target=True, selects_by_model_predictions=False,
            game_target=360000, outflow_mix='80% exact goal, 10% 380000, 10% 400000 before feasibility and band selection',
            attribute_coverage='All incoming kinds, both bank countries, every channel and compatible purpose; conditional sender constraints; full selectable waits',
            funding_coverage='Up to four receipts, optional salary; 34 energy/time, 16 actions, up to ten card transfers, 100k incoming/card, 120k cash operation and 150k total cash; conserved-flow splits and concentrations sampled before labels',
            timing_coverage='Half of original-route candidates use delayed settlement after receipt episodes; repairs insufficient low-pattern incoming-first coverage',
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
                        provenance_group_id=row.get("source_scenario_id",sid),
                        provenance=dict(root_id=row.get("source_scenario_id",sid), parent_ids=[row["source_scenario_id"]] if row.get("source_scenario_id") else []),
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
    parser.add_argument("--count", type=int, default=60000)
    args = parser.parse_args()
    build(args.output, args.count)
