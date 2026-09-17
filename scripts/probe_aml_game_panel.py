"""Small inspectable feasibility/gameplay probe before expensive dataset rebuild."""

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random

from scripts.build_aml_fixed_history_dataset import common_context
from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from src.aml_workshop_simulator.domain.scoring import (
    resource_score,
    probability_leaderboard_scores,
)


def candidate(seed):
    rng = random.Random(seed)
    config, templates = common_context()
    family = seed % len(templates)
    steps = deepcopy(templates[family]["steps"])
    topology = (seed // len(templates)) % 5
    parties = list("ABCD")
    rng.shuffle(parties)
    for i, step in enumerate(steps):
        code = step["card"]["code"]
        step["context"] = {}
        step.pop("claim_id", None)
        step["purpose_code"] = "shared_expense"
        step["interval_minutes"] = (
            None if i == 0 else rng.choices([1, 10, 60, 1440], [12, 3, 3, 1])[0]
        )
        if code == "incoming_transfer":
            step["sender_id"] = (
                parties[0] if topology in (0, 3) else rng.choice(parties)
            )
            step["action_details"] = dict(
                incoming_kind="bank_transfer", bank_country="RU"
            )
        elif code == "card_transfer":
            step["recipient_id"] = (
                parties[0]
                if topology in (1, 3)
                else parties[1]
                if topology == 0
                else rng.choice(parties)
            )
            step["action_details"] = {}
        elif code == "salary":
            step["sender_id"] = "employer"
            step["action_details"] = dict(income_basis="payroll_registry")
            step["purpose_code"] = "salary"
        else:
            step["action_details"] = {}
            step["purpose_code"] = "personal_spending"
    return config, steps, family, topology


def probe(count, output, curriculum=False, panel_v2=False):
    global PANEL_POLICY, extract_panel_features, assess_panel
    if panel_v2:
        from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
            PANEL_POLICY,
            extract_panel_features,
            assess_panel,
        )
    if output.exists():
        raise ValueError("Probe output already exists")
    rows, failures = [], Counter()
    generate = candidate
    if curriculum:
        from scripts.aml_game_curriculum import candidate as generate
    for seed in range(count):
        config, steps, family, topology = generate(2026091800 + seed)
        simulation = evaluate(steps, config)
        blockers = submit_blockers(simulation)
        if blockers:
            failures.update(e["reason"] for e in blockers)
            continue
        features = extract_panel_features(steps)
        target = assess_panel(features)
        resources = resource_score(simulation, config)
        board = probability_leaderboard_scores(
            target["target_probability"], resources, config
        )
        waiting = deepcopy(steps)
        for step in waiting[1:]:
            if step["card"]["code"] in ("card_transfer", "cash_withdrawal"):
                step["interval_minutes"] = 60
        waited = evaluate(waiting, config)
        wait_valid = not submit_blockers(waited)
        rows.append(
            dict(
                seed=2026091800 + seed,
                family=family,
                topology=topology,
                steps=steps,
                features=features,
                **target,
                resource_score=float(resources),
                game_score=float(board["game_score"]),
                waiting_valid=wait_valid,
                waited_probability=assess_panel(extract_panel_features(waiting))[
                    "target_probability"
                ]
                if wait_valid
                else None,
            )
        )
    report = dict(
        candidate_count=count,
        valid_count=len(rows),
        bands=dict(Counter(r["band"] for r in rows)),
        rejected_reasons=dict(failures),
        policy=PANEL_POLICY,
        low_families=sorted({r["family"] for r in rows if r["band"] == "low"}),
        low_resource_values=len(
            {r["resource_score"] for r in rows if r["band"] == "low"}
        ),
        waiting=dict(
            valid=sum(r["waiting_valid"] for r in rows),
            still_high=sum(
                r["waiting_valid"] and r["waited_probability"] >= 0.9 for r in rows
            ),
        ),
        pattern_support=dict(Counter(k for r in rows for k in r["rule_support"])),
        status="pilot_not_final_dataset",
        release_ready=False,
    )
    output.mkdir(parents=True)
    (output / "probe.json").write_bytes(p.json_bytes(report))
    with (output / "cases.jsonl").open("x", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--curriculum", action="store_true")
    parser.add_argument("--panel-v2", action="store_true")
    args = parser.parse_args()
    probe(args.count, args.output, args.curriculum, args.panel_v2)
