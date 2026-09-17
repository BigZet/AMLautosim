"""Add a fixed, prediction-independent grid of playable concentration cases."""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import random
from uuid import NAMESPACE_URL, uuid5

from scripts.aml_game_curriculum_v5 import catalog
from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import evaluate, submit_blockers, csv_bytes
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.domain.scoring import (
    resource_score,
    probability_leaderboard_scores,
)
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
    extract_panel_features,
    assess_panel,
)
from src.aml_workshop_simulator.core.errors import ValidationFailed


def extend(source, output):
    require(not output.exists(), "Output exists")
    audit = json.loads((source / "audit.json").read_bytes())
    for name, digest in audit["artifact_hashes"].items():
        require(file_hash(source / name) == digest, "Input artifact drift")
    for name, digest in audit["source_hashes"].items():
        require(file_hash(name) == digest, "Source drift")
    config, templates = catalog()
    require(
        config == json.loads((source / "context.json").read_bytes()), "Context drift"
    )
    rows = [
        json.loads(s)
        for s in (source / "casebook.jsonl").read_text(encoding="utf8").splitlines()
    ]
    # Re-extract instead of round-tripping numeric CSV through pandas: preserve
    # exact float values and integer types used by feature-identity grouping.
    vectors = {r["scenario_id"]: extract_panel_features(r["steps"]) for r in rows}
    seen = {
        p.digest([{k: v for k, v in s.items() if k != "step_id"} for s in r["steps"]])
        for r in rows
    }
    added, rejected = 0, Counter()
    # Same observable family; coverage spans pre-spending, recipient concentration,
    # sender count and delays. No predictions, target-band quotas or label changes.
    for pre_spend in (
        0,
        12000,
        18000,
        24000,
        30000,
        36000,
        42000,
        48000,
        54000,
        60000,
        66000,
        72000,
        78000,
    ):
        for concentration in range(70, 98, 2):
            for senders in (2, 3):
                for delay in (1, 60, 1440):
                    seed = 2052700000 + added + sum(rejected.values())
                    rng = random.Random(seed)
                    steps = deepcopy(templates[7][1])
                    cards = [s for s in steps if s["card"]["code"] == "card_transfer"]
                    incoming = [
                        s for s in steps if s["card"]["code"] == "incoming_transfer"
                    ]
                    first = Decimal(pre_spend or 36000)
                    minority = Decimal(360000) * Decimal(100 - concentration) / 100
                    # The engine rejects points exceeding an individual card limit.
                    majority_rest = Decimal(360000) - minority - first
                    amounts = [first, minority, *([majority_rest / 4] * 4)]
                    for card, amount in zip(cards, amounts):
                        card["amount"] = str(amount.quantize(Decimal(".01")))
                        card["recipient_id"] = "D"
                        card["interval_minutes"] = 1
                    cards[1]["recipient_id"] = "C"
                    for j, receipt in enumerate(incoming):
                        receipt["amount"] = str(rng.randint(78000, 80000))
                        receipt["sender_id"] = "ABC"[j % senders]
                        receipt["interval_minutes"] = 1
                    if not pre_spend:
                        steps[0], steps[1] = steps[1], steps[0]
                    for j in range(1, len(steps)):
                        if steps[j - 1]["card"]["code"] == "incoming_transfer":
                            steps[j]["interval_minutes"] = delay
                    steps[0]["interval_minutes"] = None
                    for j, step in enumerate(steps):
                        step["step_id"] = str(
                            uuid5(NAMESPACE_URL, f"concentration-{seed}-{j}")
                        )
                        step["context"] = {}
                        step.pop("claim_id", None)
                        step["purpose_code"] = "shared_expense"
                        step["action_details"] = (
                            dict(incoming_kind="bank_transfer", bank_country="RU")
                            if step["card"]["code"] == "incoming_transfer"
                            else {}
                        )
                    try:
                        snapshot = evaluate(steps, config)
                    except ValidationFailed:
                        rejected["card_or_game_constraint"] += 1
                        continue
                    blockers = submit_blockers(snapshot)
                    if blockers:
                        rejected.update(b["reason"] for b in blockers)
                        continue
                    key = p.digest(
                        [{k: v for k, v in s.items() if k != "step_id"} for s in steps]
                    )
                    require(key not in seen, "Duplicate supplement")
                    seen.add(key)
                    features = extract_panel_features(steps)
                    assessment = assess_panel(features)
                    resources = resource_score(snapshot, config)
                    board = probability_leaderboard_scores(
                        assessment["target_probability"], resources, config
                    )
                    sid = f"concentration-grid-{added:05d}"
                    rows.append(
                        dict(
                            scenario_id=sid,
                            seed=seed,
                            route_family="concentration-grid",
                            family_index=24,
                            topology="pre-spend/receipt/delayed-settlement",
                            steps=steps,
                            **assessment,
                            resource_score=float(resources),
                            reference_game_score=float(board["game_score"]),
                            context_sha256=audit["context_sha256"],
                        )
                    )
                    vectors[sid] = features
                    added += 1
    require(
        added >= 500, f"Insufficient feasible grid coverage: {added}; {dict(rejected)}"
    )
    projected = deepcopy(config)
    projected["behavior"]["history"]["operations"] = []
    closure = [
        dict(
            scenario_id=r["scenario_id"],
            provenance_group_id=r["scenario_id"],
            provenance=dict(root_id=r["scenario_id"], parent_ids=[]),
            public_snapshot=dict(config=projected, steps=r["steps"]),
        )
        for r in rows
    ]
    graph = p.connected_groups(closure, vectors)
    targets = [
        {
            **{
                k: r[k]
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
            },
            "group_id": graph["scenario_groups"][r["scenario_id"]],
            "split": "unassigned",
        }
        for r in rows
    ]
    policy = json.loads((source / "policy.json").read_bytes())
    policy["coverage_supplement"] = dict(
        rows=added,
        dimensions=["pre-spending", "recipient concentration", "sender count", "delay"],
        selects_by_target=False,
        selects_by_model_predictions=False,
        reason="Development stress test exposed sparse concentration coverage; original labels unchanged",
    )
    output.mkdir(parents=True)
    (output / "context.json").write_bytes((source / "context.json").read_bytes())
    (output / "policy.json").write_bytes(p.json_bytes(policy))
    (output / "casebook.jsonl").write_text(
        "".join(
            json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
            for r in rows
        ),
        encoding="utf8",
    )
    feature_rows = [dict(scenario_id=sid, **v) for sid, v in vectors.items()]
    (output / "features.csv").write_bytes(
        csv_bytes(list(feature_rows[0]), feature_rows)
    )
    (output / "targets.csv").write_bytes(csv_bytes(list(targets[0]), targets))
    (output / "groups.json").write_bytes(p.json_bytes(graph))
    audit["coverage_revision"] = dict(
        source=str(source),
        source_audit_sha256=file_hash(source / "audit.json"),
        added_rows=added,
        rejected=dict(rejected),
        model_predictions_used_for_selection=False,
    )
    audit["rows"] = len(rows)
    audit["groups"] = len(graph["groups"])
    audit["bands"] = dict(Counter(r["band"] for r in rows))
    votes = Counter()
    for row in rows:
        votes.update(row["rule_support"])
    audit["rule_positive_votes"] = dict(votes)
    audit["split_counts"] = {"unassigned": len(rows)}
    audit["source_hashes"][__file__] = file_hash(__file__)
    for name, digest in audit["source_hashes"].items():
        require(file_hash(name) == digest, "Source drift")
    audit["artifact_hashes"] = {
        name: file_hash(output / name) for name in audit["artifact_hashes"]
    }
    audit.pop("split_revision", None)
    (output / "audit.json").write_bytes(p.json_bytes(audit))
    print(
        json.dumps(
            dict(
                rows=len(rows),
                added=added,
                bands=audit["bands"],
                rejected=dict(rejected),
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extend(args.source, args.output)
