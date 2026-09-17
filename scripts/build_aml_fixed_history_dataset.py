"""Authored chain dataset conditional on ONE immutable game context.

Synthetic episode labels are private authored truth, not measured fraud rates.
No automatic domain approval, training, or production release is performed.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import random

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import split_groups, csv_bytes, FEATURE_NAMES
from scripts.audit_aml_history_population import require, file_hash
from src.aml_workshop_simulator.services.semantic_contract import new_config

SEED = 2026091701
BASE = Path("docs/verification/semantic-interface-audit/fixtures.json")
BEHAVIOR = Path("config/expanded_behavior.json")


def common_context():
    fixture = json.loads(BASE.read_bytes())
    baseline = json.loads(BEHAVIOR.read_bytes())
    config = new_config(fixture["config"])
    config["schema_version"] = 10
    for key in ("profile", "history", "timeline"):
        config["behavior"][key] = deepcopy(baseline[key])
    start, end = baseline["timeline"]["starts_at"], "2026-10-13T09:00:00+03:00"
    purposes = [
        "unknown",
        "loan",
        "refund",
        "asset_sale",
        "shared_expense",
        "service_payment",
        "salary",
        "personal_spending",
    ]
    # No per-scenario verification, history, profile, or counterparties are added.
    config["behavior"]["aml_context"] = dict(
        version="aml-context-v1",
        as_of=end,
        expected_activity=dict(
            period_start=start,
            period_end=end,
            activity_kinds=["salary", "shared_expense", "personal_spending"],
            expected_credit_min="0.00",
            expected_credit_max="270000.00",
            expected_debit_min="0.00",
            expected_debit_max="430000.00",
        ),
        opening_balance_facts=["opening"],
        purpose_catalog=[dict(code=x, title=x.replace("_", " ")) for x in purposes],
        facts=[
            dict(
                id="opening",
                fact_type="opening_balance",
                verification_status="verified",
                provenance="scenario_record",
                available_at=start,
                valid_from=start,
                valid_to=end,
                counterparty_ids=[],
                operation_codes=[],
                purpose_code="unknown",
                max_credit_amount="180000.00",
                max_debit_amount="180000.00",
            )
        ],
        history_coverage="complete",
        history_start="2026-08-14T09:00:00+03:00",
        history_end=start,
    )
    return config, fixture["strategies"]


def private_ledger(steps, episode):
    """Trace gross principal pro rata; engine separately verifies exact fees.

    A private pre-round offence and custody transfer is authored only for an
    illicit episode. It is NOT inserted in the player's observed bank history.
    """
    balance, criminal = Decimal(180000), Decimal(0)
    flows, first_receipt, routed = [], True, Decimal(0)
    for index, step in enumerate(steps):
        code, amount = step["card"]["code"], Decimal(step["amount"])
        tainted = Decimal(0)
        if code in ("incoming_transfer", "salary"):
            if code == "incoming_transfer" and first_receipt:
                tainted = (
                    amount if episode == "criminal_proceeds_concealment" else Decimal(0)
                )
                first_receipt = False
            balance += amount
            criminal += tainted
        else:
            require(balance >= amount, "Private principal ledger overdrawn")
            tainted = amount * criminal / balance if balance else Decimal(0)
            balance -= amount
            criminal -= tainted
            routed += tainted
        flows.append(
            dict(
                step=index + 1,
                operation=code,
                amount=str(amount),
                source=step.get("sender_id", "player"),
                beneficiary=step.get(
                    "recipient_id",
                    "player_cash" if code == "cash_withdrawal" else "player",
                ),
                criminal_principal=str(tainted),
                remaining_principal=str(balance),
            )
        )
    illicit = episode == "criminal_proceeds_concealment"
    require(not illicit or routed > 0, "Authored offence does not reach a debit")
    return dict(
        aml_episode_present=illicit,
        opening_funds="180000 lawful accumulated savings",
        episode=episode,
        upstream_events=[
            dict(
                id="offence",
                kind="misappropriation_of_entrusted_funds",
                owner="injured_owner",
                custodian=next(
                    s["sender_id"]
                    for s in steps
                    if s["card"]["code"] == "incoming_transfer"
                ),
            )
        ]
        if illicit
        else [],
        actual_payments=flows,
        criminal_principal_routed=str(routed),
        principal_accounting="Pro-rata gross-principal tracing, excludes bank fees; exact fees and resource balances checked independently by the game engine",
        legal_basis="Current lawful personal settlement obligations"
        if not illicit
        else "Claimed personal settlements conceal disposal of misappropriated principal",
    )


def generate_unit(task):
    index, variants = task
    config, strategies = common_context()
    rng = random.Random(SEED + index)
    # Episode is authored first. No heuristic score or feature threshold labels it.
    label = index % 2
    episode = "criminal_proceeds_concealment" if label else "lawful_personal_settlement"
    # Both classes deliberately include atypical and ordinary-looking chains.
    motif = rng.choices(
        ["ordinary", "distributed", "cash", "mixed"],
        [2, 3, 3, 2] if label else [6, 1, 1, 2],
    )[0]
    # These are explicit synthetic episode hypotheses, NOT observed population
    # frequencies. Known parties can offend; unfamiliar parties can be lawful.
    source_parties = rng.choices([["A", "B"], ["C", "D"]], [2, 8] if label else [8, 2])[
        0
    ]
    settlement_parties = rng.choices(
        [["A", "B"], ["C", "D"], ["A", "B", "C", "D"]],
        [2, 5, 3] if label else [7, 1, 2],
    )[0]
    templates = [
        s
        for s in strategies
        if any(x["card"]["code"] == "incoming_transfer" for x in s["steps"])
    ]
    preferred = [
        s
        for s in templates
        if (
            any(x["card"]["code"] == "cash_withdrawal" for x in s["steps"])
            if motif == "cash"
            else any(x["card"]["code"] in ("salary", "purchase") for x in s["steps"])
            if motif == "mixed"
            else sum(x["card"]["code"] == "card_transfer" for x in s["steps"]) >= 6
            if motif == "distributed"
            else not any(
                x["card"]["code"] in ("salary", "purchase") for x in s["steps"]
            )
        )
    ]
    parent = rng.choice(preferred or templates)
    rows, vectors, seen, rejected = [], {}, set(), 0
    for attempt in range(variants * 100):
        steps = deepcopy(parent["steps"])
        for pos, step in enumerate(steps):
            code = step["card"]["code"]
            step["context"] = {}
            step.pop("claim_id", None)
            step["purpose_code"] = (
                "salary"
                if code == "salary"
                else "personal_spending"
                if code in ("purchase", "cash_withdrawal")
                else rng.choice(
                    [
                        "loan",
                        "refund",
                        "shared_expense",
                        "service_payment",
                        "asset_sale",
                    ]
                )
            )
            if code == "incoming_transfer":
                step["sender_id"] = rng.choice(source_parties)
                kind = rng.choice(
                    [
                        "bank_transfer",
                        "payment_service",
                        "crypto_p2p",
                        "exchange_withdrawal",
                    ]
                )
                step["action_details"] = dict(incoming_kind=kind)
                if kind == "bank_transfer":
                    step["action_details"]["bank_country"] = rng.choice(["RU", "KG"])
                if kind == "exchange_withdrawal":
                    step["sender_id"] = "exchange"
            elif code == "card_transfer":
                step["recipient_id"] = rng.choice(settlement_parties)
                step["action_details"] = {}
            elif code == "salary":
                step["action_details"] = {
                    "income_basis": rng.choice(
                        ["employment_contract", "payroll_registry", "unknown"]
                    )
                }
            else:
                step["action_details"] = {}
            step["interval_minutes"] = (
                None if pos == 0 else rng.choices([1, 10, 60], [7, 2, 1])[0]
            )
        key = p.digest(steps)
        if key in seen:
            continue
        truth = private_ledger(steps, episode)
        truth["current_settlement_instructions"] = [
            dict(
                payment=n + 1,
                party=s.get("recipient_id", "player_cash"),
                amount=s["amount"],
                basis="current contractual liability"
                if not label
                else "nominee disposition instruction",
                instructed_by="account_holder" if not label else "offence_beneficiary",
            )
            for n, s in enumerate(steps)
            if s["card"]["code"] in ("card_transfer", "cash_withdrawal")
        ]
        sid = f"fixed-{index:05d}-{len(rows):02d}"
        row = dict(
            scenario_id=sid,
            provenance_group_id=f"fixed-origin-{index:05d}",
            family_id="P10"
            if any(s["card"]["code"] == "salary" for s in steps)
            else "P05"
            if any(s["card"]["code"] == "cash_withdrawal" for s in steps)
            else "P06",
            aml_label=label,
            label_status="confirmed",
            review_status="authored_unreviewed",
            review=None,
            author_id="fixed-context-causal-author-v1",
            label_source="authored-private-funds-origin-not-risk-rule",
            label_protocol_version="aml-labels-v1",
            population_id="aml-game-balanced-v1",
            label_rationale="Private authored ownership and gross-principal flow establish the episode; observable suspicion does not establish guilt.",
            author_truth=truth,
            public_snapshot=dict(config=config, steps=steps),
            observability=dict(
                distinguishable=False,
                reason="Common history does not reveal private current funds ownership. Identical public chains may have opposite outcomes; confidence is not guaranteed.",
            ),
            hypothesis_source=dict(
                kind="synthetic conditional episode, not empirical fraud prevalence",
                motif=motif,
            ),
            alternative_explanation=dict(
                description="The same observable transfers may settle lawful liabilities or route concealed criminal proceeds."
            ),
            necessary_facts=[
                "actual source ownership",
                "actual debit obligations",
                "custody and downstream allocation",
            ],
            forbidden_information=["private episode", "label", "origin identifier"],
            provenance=dict(root_id=f"fixed-origin-{index:05d}", parent_ids=[]),
            variant_recipe="common-context-current-chain",
        )
        try:
            feature = p.validate_sources([row], p.protocol())
        except ValueError:
            rejected += 1
            continue
        seen.add(key)
        rows.append(row)
        vectors.update(feature)
        if len(rows) == variants:
            return rows, vectors, rejected
    raise ValueError(f"Insufficient engine-valid chains for unit {index}: {len(rows)}")


def build(output, units=1500, variants=20, workers=4):
    output = Path(output)
    require(not output.exists(), "Output already exists")
    require(units % 2 == 0 and variants > 0, "Balanced even unit count required")
    config, _ = common_context()
    source_paths = [
        *p.compiler_hashes(),
        str(BASE),
        str(BEHAVIOR),
        "scripts/build_aml_fixed_history_dataset.py",
    ]
    source_hashes = {name: file_hash(name) for name in source_paths}
    output.mkdir(parents=True)
    (output / "context.json").write_bytes(p.json_bytes(config))
    context_hash = p.digest(config)
    policy = dict(
        version="fixed-history-chain-draft-v1",
        seed=SEED,
        units=units,
        variants_per_origin=variants,
        context_sha256=context_hash,
        profile=config["behavior"]["profile"],
        history_sha256=p.digest(config["behavior"]["history"]),
        source_hashes=source_hashes,
        class_assignment="Alternating privately authored episode types, not score thresholds",
        synthetic_sampling_assumptions={
            "known_source_pool_probability": {"lawful": 0.8, "illicit": 0.2},
            "settlement_pool_probabilities_A_B__C_D__all": {
                "lawful": [0.7, 0.1, 0.2],
                "illicit": [0.2, 0.5, 0.3],
            },
            "motif_probabilities_ordinary_distributed_cash_mixed": {
                "lawful": [0.6, 0.1, 0.1, 0.2],
                "illicit": [0.2, 0.3, 0.3, 0.2],
            },
            "status": "authored hypotheses, not empirical AML frequencies",
        },
        grouping="Conditional on pinned common context: root + parent + neutral chain/shape + exact feature collisions; the one global history is a conditioning constant, not evidence of separate histories",
        limitations=[
            "Synthetic authored labels, not independent domain review",
            "Same observable chain can have either hidden outcome; no promised confidence bands or narrow grey zone",
            "No forced minimum independent group count; measured closure is authoritative",
            "Probabilities learned from these assumed sampling weights are not real-world fraud probabilities",
        ],
        release_ready=False,
    )
    (output / "policy.json").write_bytes(p.json_bytes(policy))
    closure, features, labels, by_id, rejected = [], {}, Counter(), {}, 0
    digest = sha256()
    with (
        (output / "casebook.jsonl").open("xb") as handle,
        ProcessPoolExecutor(max_workers=workers) as pool,
    ):
        for index, (rows, vectors, failures) in enumerate(
            pool.map(generate_unit, ((i, variants) for i in range(units))), 1
        ):
            rejected += failures
            for row in rows:
                require(
                    p.digest(row["public_snapshot"]["config"]) == context_hash,
                    "Common context drift",
                )
                # Audit-only projection disables the global-history ancestry edge.
                # Actual exported records and their model features remain untouched.
                projected = p.closure_row(deepcopy(row))
                projected["public_snapshot"]["config"]["behavior"]["history"][
                    "operations"
                ] = []
                closure.append(projected)
                by_id[row["scenario_id"]] = {"aml_label": row["aml_label"]}
                labels[row["aml_label"]] += 1
            features.update(vectors)
            data = p.jsonl_bytes(rows)
            handle.write(data)
            digest.update(data)
            if index % 100 == 0:
                handle.flush()
                progress = dict(
                    origins=index, rows=len(closure), rejected_attempts=rejected
                )
                (output / "progress.json").write_bytes(p.json_bytes(progress))
                print(json.dumps(progress), flush=True)
    graph = p.connected_groups(closure, features)
    assignment = split_groups(graph["groups"], by_id)
    split = [
        dict(
            scenario_id=sid,
            group_id=gid,
            split=assignment[gid],
            aml_label=by_id[sid]["aml_label"],
        )
        for sid, gid in graph["scenario_groups"].items()
    ]
    collisions = defaultdict(Counter)
    for sid, vector in features.items():
        collisions[p.digest(vector)][by_id[sid]["aml_label"]] += 1
    mixed = [c for c in collisions.values() if c[0] and c[1]]
    artifacts = {
        "features.csv": csv_bytes(
            ["scenario_id", *FEATURE_NAMES],
            [dict(scenario_id=sid, **v) for sid, v in features.items()],
        ),
        "groups.json": p.json_bytes(graph),
        "split.csv": csv_bytes(
            ["scenario_id", "group_id", "split", "aml_label"], split
        ),
    }
    hashes = {
        "casebook.jsonl": digest.hexdigest(),
        "context.json": file_hash(output / "context.json"),
        "policy.json": file_hash(output / "policy.json"),
    }
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
        hashes[name] = sha256(data).hexdigest()
    require(
        all(file_hash(name) == expected for name, expected in source_hashes.items()),
        "Generation source drift",
    )
    report = dict(
        rows=len(closure),
        authored_origins=units,
        conditional_connected_groups=len(graph["groups"]),
        classes=dict(labels),
        context_count=1,
        history_count=1,
        profile_count=1,
        feature_count=len(FEATURE_NAMES),
        rejected_attempts=rejected,
        split_counts=dict(Counter(r["split"] for r in split)),
        conflicting_feature_vectors=len(mixed),
        conflicting_feature_rows=sum(sum(c.values()) for c in mixed),
        artifact_hashes=hashes,
        source_hashes=source_hashes,
        reviewed_rows=0,
        release_ready=False,
        limitations=policy["limitations"],
    )
    (output / "audit.json").write_bytes(p.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--units", type=int, default=1500)
    parser.add_argument("--variants", type=int, default=20)
    args = parser.parse_args()
    report = build(args.output, args.units, args.variants)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "rows",
                    "conditional_connected_groups",
                    "classes",
                    "release_ready",
                )
            }
        )
    )
