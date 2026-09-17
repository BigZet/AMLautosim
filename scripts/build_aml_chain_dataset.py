"""Paired economic episodes with a fixed history and chain-first variation.

Educational authored population, not empirical fraud prevalence. Context is
stored once; hydrate() restores the standard casebook contract for validation.
"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import random
from uuid import NAMESPACE_URL, uuid5

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import FEATURE_NAMES, csv_bytes, split_groups
from scripts.audit_aml_history_population import file_hash, require
from scripts.build_aml_fixed_history_dataset import common_context, private_ledger

SEED = 2026091801
FAMILIES = (
    "repeated_relay",
    "collection_distribution",
    "consolidation",
    "cash_conversion",
    "return_cycle",
    "mixed_personal_flow",
)
LAWFUL = (
    "Instalments for personal renovation paid against completed milestones",
    "Reimbursement of household costs advanced from personal savings",
    "Repayment of a documented personal loan to one creditor",
    "Cash reserved for agreed household purchases before reimbursements arrive",
    "Refund of an overpayment with independent scheduled personal obligations",
    "Personal expense settlement alongside salary and household spending",
)
ILLICIT = (
    "Repeated forwarding of diverted escrow proceeds to instructed nominees",
    "Accumulation of diverted proceeds before coordinated distribution",
    "Collection of diverted proceeds and consolidation to a controller",
    "Conversion of diverted proceeds into cash for delivery to a controller",
    "Return of diverted proceeds to a custodian under false settlement claims",
    "Concealment of a diversion flow among ordinary personal transactions",
)


def hydrate(row, context):
    require(row.get("context_sha256") == p.digest(context), "Context binding mismatch")
    result = deepcopy(row)
    result["public_snapshot"]["config"] = context
    return result


def make_steps(index, variant, attempt, label):
    """Both classes have identical operation/amount/party multisets per pair.

    Only scheduling changes. Party identity, channel and purpose are nuisance
    draws shared by the pair, never chosen from class-dependent pools.
    """
    rng = random.Random(SEED + index * 100003 + variant * 1009 + attempt * 17)
    family = index % len(FAMILIES)
    parties = list("ABCD")
    rng.shuffle(parties)
    credits, debits = [], []

    def step(code, amount, n):
        card_id = {
            "incoming_transfer": 2,
            "card_transfer": 3,
            "cash_withdrawal": 4,
            "salary": 1,
            "purchase": 5,
        }[code]
        return dict(
            step_id=str(uuid5(NAMESPACE_URL, f"chain/{index}/{variant}/{attempt}/{n}")),
            card=dict(id=card_id, code=code, version=1),
            amount=f"{amount:.2f}",
            context={},
            action_details={},
            purpose_code="shared_expense",
        )

    for i in range(3):
        s = step("incoming_transfer", rng.randrange(77000, 80001), i)
        s["sender_id"] = parties[i % (1 if family == 0 else 3)]
        kind = rng.choice(["bank_transfer", "payment_service", "crypto_p2p"])
        s["action_details"] = {"incoming_kind": kind}
        if kind == "bank_transfer":
            s["action_details"]["bank_country"] = rng.choice(["RU", "KG"])
        credits.append(s)
    # Same cash exposure in both classes: cash itself is not the label.
    cash = rng.randrange(60000, 100001) if family == 3 else 0
    count = 5 if cash or family == 5 else 6
    remaining = 400000 - cash
    amounts = [remaining // count] * count
    amounts[-1] += remaining - sum(amounts)
    for i in range(count - 1):
        delta = rng.randrange(-6500, 6501)
        if (
            10000 <= amounts[i] + delta <= 79500
            and 10000 <= amounts[-1] - delta <= 79500
        ):
            amounts[i] += delta
            amounts[-1] -= delta
    for i, amount in enumerate(amounts):
        s = step("card_transfer", amount, 3 + i)
        s["recipient_id"] = parties[0 if family in (2, 4) else (i + 1) % 4]
        s["context"]["channel"] = rng.choice(["mobile", "web"])
        debits.append(s)
    if cash:
        s = step("cash_withdrawal", cash, 9)
        s.update(context={"channel": "atm"}, purpose_code="personal_spending")
        debits.insert(0, s)

    # Overlap is authored as real alternative economics, not removed as noise.
    ambiguous = index % 10 == 0
    urgent_lawful = index % 10 == 1
    patient_illicit = index % 10 == 2
    relay_schedule = bool(label)
    if ambiguous or urgent_lawful:
        relay_schedule = True
    if patient_illicit:
        relay_schedule = False
    if relay_schedule:
        if family in (1, 2):
            separator = step("purchase", 1000, 12)
            separator.update(recipient_id="shop", purpose_code="personal_spending")
            sequence = [
                *credits[:2],
                *debits[:2],
                separator,
                *debits[2:4],
                credits[2],
                *debits[4:],
            ]
        else:
            sequence = [
                credits[0],
                *debits[:2],
                credits[1],
                *debits[2:4],
                credits[2],
                *debits[4:],
            ]
    else:
        sequence = [
            *debits[:2],
            credits[0],
            debits[2],
            credits[1],
            debits[3],
            credits[2],
            *debits[4:],
        ]
        if family in (1, 2):
            separator = step("purchase", 1000, 12)
            separator.update(recipient_id="shop", purpose_code="personal_spending")
            sequence.insert(4, separator)
    # Salaries/purchases appear in both classes and never whitewash other flows.
    if family == 5:
        salary = step("salary", 25000, 10)
        salary.update(
            sender_id="employer",
            purpose_code="salary",
            action_details={"income_basis": "payroll_registry"},
        )
        purchase = step("purchase", 3000, 11)
        purchase.update(recipient_id="shop", purpose_code="personal_spending")
        sequence = [salary, *sequence[:4], purchase, *sequence[4:]]
    for position, s in enumerate(sequence):
        s["interval_minutes"] = None if position == 0 else 1
        if not relay_schedule and position in (2, 5):
            s["interval_minutes"] = rng.choice([10, 60, 1440])
        elif relay_schedule and position == 4:
            s["interval_minutes"] = rng.choice([1, 10])
    return sequence, dict(
        ambiguous_pair=ambiguous,
        urgent_lawful=urgent_lawful,
        patient_illicit=patient_illicit,
        relay_schedule=relay_schedule,
    )


def record(index, variant, label, steps, mode, context):
    family = index % len(FAMILIES)
    sid = f"chain-{index:05d}-{variant:02d}-{label}"
    truth = private_ledger(
        steps,
        "criminal_proceeds_concealment" if label else "lawful_personal_settlement",
    )
    truth["economic_episode"] = ILLICIT[family] if label else LAWFUL[family]
    truth["source_title"] = {
        "owner": "escrow_principal" if label else "account_holder",
        "authorization": "custodian diverted entrusted money without owner's consent"
        if label
        else "payer settles an actual personal sale or reimbursement debt",
        "evidence_status": "authored_private_event_not_observed_document",
    }
    truth["settlement_obligations"] = [
        dict(
            operation_id=s["step_id"],
            amount=s["amount"],
            beneficiary=s.get("recipient_id", "account_holder_cash"),
            actual_basis=truth["economic_episode"],
            authorized_by="offence_controller" if label else "account_holder",
            contractual_claim_genuine=not bool(label),
        )
        for s in steps
        if s["card"]["code"] in ("card_transfer", "cash_withdrawal")
    ]
    return dict(
        scenario_id=sid,
        provenance_group_id=f"chain-origin-{index:05d}",
        family_id="P05" if family == 3 else "P10" if family == 5 else "P06",
        chain_family=FAMILIES[family],
        aml_label=label,
        label_status="confirmed",
        review_status="authored_unreviewed",
        review=None,
        author_id="chain-economic-author-v2",
        label_source="private-economic-episode-v2",
        label_protocol_version="aml-labels-v1",
        population_id="aml-game-balanced-v1",
        label_rationale="Class follows authored diversion and disposal, not a behavioral score; scheduling follows the economic scenario. Sampling is educational, not empirical.",
        author_truth=truth,
        public_snapshot=dict(config=context, steps=steps),
        observability=dict(
            distinguishable=False,
            reason="Chain behavior supplies statistical evidence in this authored population, not proof of hidden ownership; lawful urgency and patient concealment overlap.",
        ),
        hypothesis_source=dict(kind="authored chain process", **mode),
        alternative_explanation=dict(
            description=LAWFUL[family] if label else ILLICIT[family]
        ),
        necessary_facts=[
            "actual source title",
            "authorization",
            "actual settlement obligation",
        ],
        forbidden_information=[
            "author_truth",
            "chain_family",
            "scenario_id",
            "aml_label",
        ],
        provenance=dict(
            root_id=f"chain-origin-{index:05d}",
            parent_ids=[],
            counterfactual_pair_id=f"chain-pair-{index:05d}-{variant:02d}",
        ),
        variant_recipe="paired-amounts-parties-channels-chain-schedule-v2",
    )


def generate_unit(task):
    index, variants = task
    context, _ = common_context()
    rows, features, rejected = [], {}, 0
    for variant in range(variants):
        for attempt in range(100):
            pair = []
            for label in (0, 1):
                steps, mode = make_steps(index, variant, attempt, label)
                pair.append(record(index, variant, label, steps, mode, context))
            try:
                vectors = p.validate_sources(pair, p.protocol())
            except ValueError:
                rejected += 1
                continue
            rows.extend(pair)
            features.update(vectors)
            break
        else:
            raise ValueError(f"No valid matched pair: {index}/{variant}")
    return rows, features, rejected


def build(output, units=1500, variants=10, workers=4):
    output = Path(output)
    require(not output.exists(), "Output already exists")
    require(units >= 10 and variants > 0, "Insufficient population")
    context, _ = common_context()
    context_hash = p.digest(context)
    source_names = {
        *p.compiler_hashes(),
        "scripts/build_aml_chain_dataset.py",
        "scripts/build_aml_fixed_history_dataset.py",
        "config/expanded_behavior.json",
    }
    source_hashes = {name: file_hash(name) for name in source_names}
    output.mkdir(parents=True)
    (output / "context.json").write_bytes(p.json_bytes(context))
    policy = dict(
        version="chain-economic-v2",
        format="context-reference-jsonl-v1",
        context_sha256=context_hash,
        seed=SEED,
        units=units,
        variants=variants,
        source_hashes=source_hashes,
        families=list(FAMILIES),
        release_ready=False,
        class_definition="authored unauthorized diversion followed by disposal versus genuine personal obligations",
        sampling="balanced paired educational processes, not real AML prevalence",
        nuisance_balance="same operation amounts, sender/recipient IDs, channels, incoming kinds and purposes within each class pair",
        overlap="10% origins identical observations, 10% urgent lawful paired with relay, 10% patient illicit paired with staged settlement; proportions are authored stress assumptions",
        grouping="root + counterfactual pairs + neutral chain/shape + exact features, conditional on one immutable history",
    )
    (output / "policy.json").write_bytes(p.json_bytes(policy))
    projected_context = deepcopy(context)
    projected_context["behavior"]["history"]["operations"] = []
    closure, vectors, labels, rejected = [], {}, {}, 0
    with (output / "casebook.jsonl").open("x", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for n, (rows, features, failures) in enumerate(
                pool.map(generate_unit, ((i, variants) for i in range(units))), 1
            ):
                rejected += failures
                vectors.update(features)
                for row in rows:
                    require(
                        p.digest(row["public_snapshot"]["config"]) == context_hash,
                        "Context drift",
                    )
                    projected = p.closure_row(row)
                    projected["public_snapshot"] = dict(
                        config=projected_context, steps=row["public_snapshot"]["steps"]
                    )
                    closure.append(projected)
                    labels[row["scenario_id"]] = {"aml_label": row["aml_label"]}
                    row["context_sha256"] = context_hash
                    row["public_snapshot"].pop("config")
                    handle.write(
                        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                if n % 100 == 0:
                    print(
                        json.dumps(
                            dict(origins=n, rows=len(labels), rejected_pairs=rejected)
                        ),
                        flush=True,
                    )
    graph = p.connected_groups(closure, vectors)
    assignment = split_groups(graph["groups"], labels)
    split = [
        dict(scenario_id=sid, group_id=gid, split=assignment[gid], **labels[sid])
        for sid, gid in graph["scenario_groups"].items()
    ]
    for name, content in {
        "features.csv": csv_bytes(
            ["scenario_id", *FEATURE_NAMES],
            [dict(scenario_id=sid, **v) for sid, v in vectors.items()],
        ),
        "split.csv": csv_bytes(
            ["scenario_id", "group_id", "split", "aml_label"], split
        ),
        "groups.json": p.json_bytes(graph),
    }.items():
        (output / name).write_bytes(content)
    require(
        all(file_hash(name) == value for name, value in source_hashes.items()),
        "Source drift",
    )
    report = dict(
        rows=len(labels),
        classes=dict(Counter(r["aml_label"] for r in labels.values())),
        conditional_groups=len(graph["groups"]),
        rejected_pairs=rejected,
        split_counts=dict(Counter(r["split"] for r in split)),
        source_hashes=source_hashes,
        artifact_hashes={
            name: file_hash(output / name)
            for name in (
                "context.json",
                "policy.json",
                "casebook.jsonl",
                "features.csv",
                "split.csv",
                "groups.json",
            )
        },
        release_ready=False,
        reviewed_rows=0,
    )
    (output / "audit.json").write_bytes(p.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--units", type=int, default=1500)
    parser.add_argument("--variants", type=int, default=10)
    args = parser.parse_args()
    result = build(args.output, args.units, args.variants)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("rows", "classes", "conditional_groups", "split_counts")
            }
        )
    )
