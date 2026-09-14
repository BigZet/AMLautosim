"""A new, group-disjoint behavior dataset. Approved rubric and old release are read-only."""

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from copy import deepcopy
from itertools import combinations
from pathlib import Path
from uuid import UUID

from scripts.aml_dataset.expanded import digest, fingerprint, label, rubric, valid
from scripts.aml_dataset.review_contexts import context_variant
from scripts.check_expanded_balance import demo_config
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import (
    extract_features,
    FEATURE_VERSION,
)

PROTOCOL = Path("config/ml/behavior-v2-protocol.json")
BASIS = ("payroll_registry", "service_contract", "no_reference")
VERSION = "behavior-coverage-v3-1"


def dump(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def topology(steps):
    return "".join(
        "C" if s["card"]["code"] == "incoming_transfer" else "D"
        for s in steps
        if s["card"]["code"]
        in ("incoming_transfer", "card_transfer", "cash_withdrawal")
    )


def build_groups(seed, old_topologies):
    rng = random.Random(seed)
    groups = []
    for n in (5, 6, 7, 8, 9, 10):
        eligible = []
        for positions in combinations(range(n + 3), 3):
            shape = "".join("C" if i in positions else "D" for i in range(n + 3))
            if "CCC" in shape:
                continue
            balance = 180000
            for code in shape:
                balance += 78000 if code == "C" else -400000 / n
                if balance < -1e-6:
                    break
            else:
                eligible.append(shape)
        rng.shuffle(eligible)
        # Old reviewed shapes may be development data, never the fresh test.
        known = [s for s in eligible if s in old_topologies]
        unseen = [s for s in eligible if s not in old_topologies]
        train_count, held_count = 16, 4
        if (
            len(known) > train_count
            or len(known) + len(unseen) < train_count + 2 * held_count
        ):
            raise ValueError("Insufficient independent skeletons")
        reserved = (
            [shape for shape in unseen if "DDD" not in shape][:2] if n <= 8 else []
        )
        pool = [shape for shape in unseen if shape not in reserved]
        train = known + pool[: train_count - len(known)]
        rest = pool[train_count - len(known) :]
        validation = reserved[:1] + rest[: held_count - min(1, len(reserved))]
        rest = rest[held_count - min(1, len(reserved)) :]
        test = reserved[1:2] + rest[: held_count - min(1, max(0, len(reserved) - 1))]
        for split, shapes in [
            ("train", train),
            ("validation", validation),
            ("test", test),
        ]:
            for shape in shapes:
                groups.append(
                    {
                        "group": digest(shape)[:16],
                        "shape": shape,
                        "split": split,
                        "debit_count": n,
                    }
                )
    return groups


def step(cards, code, amount, sender=None, recipient=None, details=None):
    return dict(
        card={k: cards[code][k] for k in ("id", "code", "version")},
        amount=f"{amount:.2f}",
        context={},
        action_details=details or {},
        sender_id=sender,
        recipient_id=recipient,
        interval_minutes=1,
    )


def reset_ids(steps):
    for i, item in enumerate(steps):
        item["step_id"] = str(UUID(int=i + 1))
        item["interval_minutes"] = None if i == 0 else item.get("interval_minutes") or 1
    return steps


def allocate(rng, total, maxima):
    values = [10000] * len(maxima)
    remaining = total - sum(values)
    indices = list(range(len(values)))
    while remaining:
        rng.shuffle(indices)
        changed = False
        for i in indices:
            capacity = maxima[i] - values[i]
            if not capacity:
                continue
            amount = min(remaining, capacity, rng.randrange(1000, 16001, 1000))
            values[i] += amount
            remaining -= amount
            changed = True
            if not remaining:
                break
        if not changed:
            raise ValueError("Infeasible bounded allocation")
    return values


def packet(rng, group, base_config, cards, block):
    config = context_variant(base_config, rng.randrange(8))
    n = group["debit_count"]
    min_cash = max(0, n - 8)
    cash_count = rng.randint(min_cash, min(4, n - 4))
    cash_positions = set(rng.sample(range(n), cash_count))
    card_count = n - cash_count
    max_target = min(406000, card_count * 80000 + min(120000, cash_count * 100000))
    target = rng.randrange(400000, max_target + 1, 1000)
    if cash_count:
        low = max(cash_count * 10000, target - card_count * 80000)
        high = min(120000, cash_count * 100000, target - card_count * 10000)
        cash_total = rng.randrange(low, high + 1, 1000)
        cash_amounts = iter(allocate(rng, cash_total, [100000] * cash_count))
    else:
        cash_total = 0
        cash_amounts = iter([])
    card_amounts = iter(allocate(rng, target - cash_total, [80000] * card_count))
    amounts = [
        next(cash_amounts) if i in cash_positions else next(card_amounts)
        for i in range(n)
    ]
    incoming = [rng.randrange(77000, 80001, 1000) for _ in range(3)]
    party = rng.choice(["A", "B", "C", "D"]) if rng.random() < 0.6 else None
    values, ci, di = [], 0, 0
    for code in group["shape"]:
        if code == "C":
            item = step(
                cards,
                "incoming_transfer",
                incoming[ci],
                sender=party or rng.choice(["A", "B", "C", "D"]),
                details={
                    "transfer_source": rng.choice(
                        [
                            "domestic_bank",
                            "payment_service",
                            "crypto_exchange",
                            "foreign_bank_kg",
                        ]
                    )
                },
            )
            ci += 1
        else:
            code = "cash_withdrawal" if di in cash_positions else "card_transfer"
            item = step(
                cards,
                code,
                amounts[di],
                recipient=(party or rng.choice(["A", "B", "C", "D"]))
                if code == "card_transfer"
                else None,
            )
            di += 1
        channels = cards[item["card"]["code"]]["channels"]
        if channels:
            item["context"]["channel"] = rng.choice(channels)
        item["interval_minutes"] = rng.choices([1, 10, 60, 1440], [86, 7, 6, 1])[0]
        values.append(item)
    # A broad mix, chosen without looking at labels or predictions.
    for _ in range(rng.choices([0, 1, 2, 3], [55, 25, 12, 8])[0]):
        purchase = step(
            cards, "purchase", rng.choice([1000, 2000, 3000]), recipient="shop"
        )
        values.insert(rng.randrange(1, len(values) + 1), purchase)
    reset_ids(values)
    members = [("base", values)]
    if n <= 6:
        position = rng.choice([len(values), 0, rng.randrange(len(values) + 1)])
        amount = rng.choice([20000, 25000, 30000])
        for basis in BASIS:
            changed = deepcopy(values)
            changed.insert(
                position,
                step(
                    cards,
                    "salary",
                    amount,
                    sender="employer",
                    details={"income_basis": basis},
                ),
            )
            members.append((basis, reset_ids(changed)))
    changed = deepcopy(values)
    destination = "C" if party in ("A", "B", None) else "A"
    for item in changed:
        if item["card"]["code"] == "incoming_transfer":
            item["sender_id"] = destination
        elif item["card"]["code"] == "card_transfer":
            item["recipient_id"] = destination
    members.append(("party", reset_ids(changed)))
    if any(not valid(v, config) for _, v in members):
        return None
    # Additional paired diagnostics remain in the same C/D parent group.
    if block % 8 == 0:
        for kind in ("interval", "purchase", "order", "source"):
            changed = deepcopy(values)
            if kind == "interval":
                for item in changed[1:]:
                    item["interval_minutes"] = 1
                changed[1]["interval_minutes"] = 60
            elif kind == "purchase":
                changed.append(step(cards, "purchase", 1000, recipient="shop"))
            elif kind == "order":
                indices = [
                    i
                    for i, s in enumerate(changed)
                    if s["card"]["code"] in ("card_transfer", "cash_withdrawal")
                ]
                a, b = rng.sample(indices, 2)
                changed[a], changed[b] = changed[b], changed[a]
            else:
                next(s for s in changed if s["card"]["code"] == "incoming_transfer")[
                    "action_details"
                ]["transfer_source"] = "crypto_exchange"
            reset_ids(changed)
            if valid(changed, config):
                members.append((kind, changed))
    return config, members


def make_record(identity, values, config, parent, kind, rules):
    values = canonical_expanded_steps(values, config)
    features = extract_features(values, config)
    target, explanation = label(features, rules)
    return dict(
        id=identity,
        group=parent["group"],
        split=parent["split"],
        kind=kind,
        steps=values,
        config_snapshot=config,
        observable_hash=fingerprint(values, config),
        features=features,
        target_risk_score=target,
        explanation=explanation,
    )


def generate(output):
    output = Path(output)
    if output.exists():
        raise ValueError("Output must be new")
    protocol = json.loads(PROTOCOL.read_text())
    rules = rubric()
    if rules["version"] != protocol["rubric"]:
        raise ValueError("Rubric version changed")
    old_hashes, old_topologies = set(), set()
    with Path("resources/aml_dataset/release-v2-1/scenarios.jsonl").open() as file:
        for line in file:
            record = json.loads(line)
            old_hashes.add(record["observable_hash"])
            old_topologies.add(topology(record["steps"]))
    for line in (
        Path("resources/aml_dataset/review-v2-final-1/pairs.jsonl")
        .read_text()
        .splitlines()
    ):
        pair = json.loads(line)
        old_topologies.update(topology(pair[s]["steps"]) for s in ("before", "after"))
    groups = build_groups(protocol["dataset_seed"], old_topologies)
    output.mkdir(parents=True)
    dump(output / "protocol.json", protocol)
    dump(output / "groups.json", groups)
    dump(output / "rubric.json", rules)
    config = demo_config()
    dump(output / "base-config.json", config)
    cards = {s["code"]: s for s in config["card_snapshots"]}
    rows, pairs, seen = [], [], set(old_hashes)
    rejected = Counter()
    for gindex, group in enumerate(groups):
        rng = random.Random(protocol["dataset_seed"] + int(group["group"], 16))
        required = (
            protocol["blocks_per_low_count_group"]
            if group["debit_count"] <= 6
            else protocol["blocks_per_high_count_group"]
        )
        accepted = 0
        for attempt in range(required * 200):
            generated = packet(rng, group, config, cards, accepted)
            if generated is None:
                rejected["invalid_packet"] += 1
                continue
            config_snapshot, members = generated
            prepared = []
            for kind, steps in members:
                identity = f"{group['group']}-{accepted:03}-{kind}"
                prepared.append(
                    make_record(identity, steps, config_snapshot, group, kind, rules)
                )
            # A redundant source/party variant adds no duplicate row.
            core = [r for r in prepared if r["kind"] in ("base", *BASIS)]
            if any(r["observable_hash"] in seen for r in core):
                rejected["duplicate_core"] += 1
                continue
            base = prepared[0]
            for row in prepared:
                if row["observable_hash"] in seen:
                    rejected["duplicate_variant"] += 1
                    continue
                seen.add(row["observable_hash"])
                rows.append(row)
                if row["kind"] != "base":
                    pairs.append(
                        dict(
                            group=group["group"],
                            split=group["split"],
                            kind=row["kind"],
                            before=base["id"],
                            after=row["id"],
                        )
                    )
            accepted += 1
            if accepted == required:
                break
        if accepted != required:
            raise ValueError(f"Insufficient valid blocks: {group}: {accepted}")
        print(
            f"group {gindex + 1}/{len(groups)} {group['split']} D={group['debit_count']}; rows={len(rows)}",
            flush=True,
        )
    # Constants are learned on train only, never from held-out labels or features.
    columns = [
        k
        for k in rows[0]["features"]
        if len({str(r["features"][k]) for r in rows if r["split"] == "train"}) > 1
    ]
    if "income_basis" not in columns:
        raise ValueError("Income coverage missing")
    dump(
        output / "feature-schema.json",
        dict(version=FEATURE_VERSION, columns=columns, categorical=["income_basis"]),
    )
    with (
        (output / "scenarios.jsonl").open("w") as raw,
        (output / "features.csv").open("w") as features,
        (output / "split.csv").open("w") as splits,
    ):
        fw = csv.DictWriter(features, fieldnames=columns + ["target_risk_score"])
        fw.writeheader()
        sw = csv.DictWriter(splits, fieldnames=["row_index", "id", "group", "split"])
        sw.writeheader()
        for i, row in enumerate(rows):
            raw.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            fw.writerow(
                {
                    **{k: row["features"][k] for k in columns},
                    "target_risk_score": row["target_risk_score"],
                }
            )
            sw.writerow(
                dict(row_index=i, id=row["id"], group=row["group"], split=row["split"])
            )
    dump(output / "pairs.json", pairs)
    coverage = {}
    for split in ("train", "validation", "test"):
        part = [r for r in rows if r["split"] == split]
        coverage[split] = dict(
            rows=len(part),
            groups=len({r["group"] for r in part}),
            salary=dict(Counter(r["features"]["income_basis"] for r in part)),
            cash=dict(
                Counter(
                    str(int(r["features"]["count_cash_withdrawal"] > 0)) for r in part
                )
            ),
        )
        if (
            min(coverage[split]["salary"].get(b, 0) for b in ("absent", *BASIS))
            < protocol["min_subgroup_rows"]
        ):
            raise ValueError("Insufficient income coverage")
        if (
            min(coverage[split]["cash"].get(str(b), 0) for b in (0, 1))
            < protocol["min_subgroup_rows"]
        ):
            raise ValueError("Insufficient cash coverage")
    dump(
        output / "manifest.json",
        dict(
            version=VERSION,
            extractor=FEATURE_VERSION,
            rubric=rules["version"],
            count=len(rows),
            coverage=coverage,
            rejections=dict(rejected),
            old_release_overlap=0,
            unique_observable_hashes=len(rows),
        ),
    )
    checksums = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.iterdir())
        if p.is_file()
    }
    dump(output / "CHECKSUMS.json", checksums)
    print("DATASET COMPLETE", coverage, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", required=True)
    generate(parser.parse_args().output)
