"""Review-only v8 dataset. No pilot or release is authorized by this module."""

import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from scripts.check_expanded_balance import demo_config, demo_steps
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
    score_expanded_scenario,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v2 import (
    FEATURE_VERSION,
    extract_features,
)

ROOT = Path(__file__).resolve().parents[2]
GENERATOR_VERSION = "expanded-review-v2-final-1"
FAMILIES = [
    "Распоряжение средствами",
    "Поступления и переводы",
    "Поступления и наличные",
    "Повторяющиеся списания",
    "Смешанные источники",
    "Неоднозначные сочетания",
]
SOURCES = {
    "USER": "../../../docs/verification/aml-rubric-feedback-2026-09-14.md",
    "S6": "https://www.fincen.gov/system/files/2025-08/FinCEN-Advisory-CMLN-508.pdf",
    "S7": "https://bsaaml.ffiec.gov/manual/Appendices/07",
}


def stable(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def digest(value):
    return hashlib.sha256(stable(value).encode()).hexdigest()


def rubric():
    return json.loads((ROOT / "config/synthetic_dataset/v2/rubric.json").read_text())


def label(features, rules, _pace_reference=False):
    signals = dict(features)
    signals["history_unknown"] = 1 - features["history_known"]
    scale = rules.get("activity_scaling")
    if scale:
        debits = features["count_card_transfer"] + features["count_cash_withdrawal"]
        volume = min(features["target_outflow"] / scale["full_volume"], 1)
        signals["activity_scale"] = volume * min(debits / scale["full_debit_count"], 1)
        signals["transit_strength"] = (
            signals["activity_scale"]
            * min(features["credit_debit_links"] / scale["full_credit_debit_links"], 1)
        )
        background = (
            features["history_salary_count"] + features["history_purchase_count"]
        )
        signals["background_deficit"] = (
            (1 - min(background / scale["full_background_events"], 1))
            if features["history_known"]
            else 0
        )
    terms = []
    signals["amount_growth"] = (
        min(1, max(0, (features["debit_mean_history_ratio"] - 2) / 3))
        if features["history_has_debits"] else 0
    )
    signals["repeated_return_cycles"] = min(1, max(0, features["observed_return_cycle_count"] - 1) / 2)
    episode_policy = rules["matched_flow"]
    large = features["matched_large_episode_count"]
    fast_points = episode_policy["large_points"][min(large, 3)]
    slow_points = min(large, 3)
    small_points = min(5, max(0, features["matched_small_max_run"] - 4))
    context_factor = .5 if (not features["history_known"] or features["history_stable_background"]) else 1
    return_points = signals["repeated_return_cycles"] * 8 * signals["activity_scale"]
    combined = min(10, fast_points + small_points + return_points) * context_factor
    timed = min(10, slow_points + (fast_points - slow_points)
                * features["matched_large_tempo_mean"] + small_points + return_points) * context_factor
    signals["matched_flow_points"] = combined
    episode_waiting_reduction = combined - timed
    signals["recipient_breadth"] = min(1, max(0, features["unique_recipients"] - 3) / 2)
    for term in rules["terms"]:
        signal = signals[term["feature"]]
        interaction = signals[term["interact"]] if term.get("interact") else 1
        contribution = signal * interaction * term["weight"]
        terms.append(
            dict(
                name=term["name"],
                signal=signal,
                interaction=interaction,
                contribution=round(contribution, 6),
                sources=[SOURCES[s] for s in term["sources"]],
            )
        )
    subtotal = max(0, sum(t["contribution"] for t in terms))
    intensity = rules.get("intensive_activity")
    if intensity:
        strength = signals["transit_strength"]
        # Activity has its own contribution even when party information is sufficient.
        # Saturation prevents adding a flat ten points to already-high assessments.
        addition = max(
            0,
            intensity["floor"] * strength - subtotal,
            min(intensity["max_addition"],
                max(0, (intensity["saturation_score"] - subtotal) / 2)) * strength,
        )
        if addition:
            terms.append(dict(name="Интенсивная транзакционная активность",
                              signal=strength, interaction=1,
                              contribution=round(addition, 6), sources=[SOURCES["USER"]]))
        subtotal = max(0, sum(t["contribution"] for t in terms))
    discount = (
        rules.get("salary_discount", {}).get(features.get("income_basis"), 0)
        if features.get("count_salary", 0)
        else 0
    )
    if discount:
        terms.append(
            dict(
                name="Снижение за текущую зарплату",
                signal=discount,
                interaction=subtotal,
                contribution=round(-subtotal * discount, 6),
                sources=[SOURCES["USER"]],
            )
        )
    purchase_policy = rules.get("purchase_background")
    if (
        purchase_policy
        and features["count_purchase"] > 0
        and features["target_outflow"] > 0
    ):
        count_factor = min(
            features["count_purchase"] / purchase_policy["full_purchase_count"],
            1,
        )
        spend_factor = min(
            features["purchase_total"]
            / (features["target_outflow"] * purchase_policy["full_spend_share"]),
            1,
        )
        remaining = max(0, sum(t["contribution"] for t in terms))
        reduction = min(
            remaining, purchase_policy["max_points"] * count_factor * spend_factor
        )
        terms.append(
            dict(
                name="Небольшой эффект текущих покупок",
                signal=count_factor,
                interaction=spend_factor,
                contribution=round(-reduction, 6),
                sources=[SOURCES["USER"]],
            )
        )
    subtotal = sum(t["contribution"] for t in terms)
    bounded = min(100, max(0, subtotal))
    if bounded != subtotal:
        terms.append(dict(name="Ограничение шкалы 0–100", signal=1,
                          interaction=1, contribution=bounded - subtotal, sources=[]))
    waiting = rules.get("waiting_discount")
    if waiting and features["credit_debit_links"]:
        fraction = min(1, max(0,
            features[waiting["feature"]] / waiting["normalization_minutes"]))
        # Both temporal effects share the previously agreed total 15% ceiling.
        reduction = min(bounded * waiting["max_fraction"],
                        bounded * waiting["max_fraction"] * fraction
                        + episode_waiting_reduction * (1 - discount))
        if reduction:
            terms.append(dict(name="Ограниченный эффект ожидания", signal=fraction,
                              interaction=waiting["max_fraction"],
                              contribution=-reduction, sources=[SOURCES["USER"]]))
        bounded -= reduction
    if waiting and not _pace_reference:
        reference = dict(features)
        for key, value in features.items():
            if key.startswith("pace_reference_"):
                reference[key.removeprefix("pace_reference_")] = value
        reference[waiting["feature"]] = 0
        reference_score = label(reference, rules, _pace_reference=True)[0]
        floor = reference_score * (1 - waiting["max_fraction"])
        if bounded < floor:
            terms.append(dict(name="Общий предел эффекта времени",
                              signal=waiting["max_fraction"], interaction=reference_score,
                              contribution=floor - bounded, sources=[SOURCES["USER"]]))
            bounded = floor
    return round(bounded, 4), terms


def fingerprint(steps, config):
    """Observable chain+snapshot invariant to transport IDs and catalogue ordering.

    First appearance numbers preserve the identity graph, including equal-looking parties.
    Unused catalogue entries are sorted by attributes; they never join an observed edge.
    """
    values = deepcopy(canonical_expanded_steps(steps, config))
    snapshot = deepcopy(config)
    snapshot.pop("config_version", None)
    parties = {p["id"]: p for p in snapshot["behavior"]["counterparties"]}
    mapping = {}

    def identity(original):
        if original is None:
            return None
        if original not in mapping:
            mapping[original] = f"p{len(mapping)}"
        return mapping[original]

    for step in values:
        step.pop("step_id", None)
        step["card"].pop("id", None)
        for key in ("sender_id", "recipient_id"):
            step[key] = identity(step.get(key))
    for event in snapshot["behavior"]["history"]["operations"] or []:
        event.pop("id", None)
        event["counterparty_id"] = identity(event.get("counterparty_id"))
    observed = [
        {**{k: v for k, v in parties[p].items() if k != "id"}, "id": mapped}
        for p, mapped in mapping.items()
    ]
    unused = sorted(
        (
            {k: v for k, v in p.items() if k != "id"}
            for k, p in parties.items()
            if k not in mapping
        ),
        key=stable,
    )
    snapshot["behavior"]["counterparties"] = {"observed": observed, "unused": unused}
    snapshot["behavior"]["profile"].pop("id", None)
    for card in snapshot["card_snapshots"]:
        card.pop("id", None)
    return digest({"steps": values, "config": snapshot})


def topology(steps):
    # Purchases/salary variants remain related to their financial template.
    return tuple(
        s["card"]["code"]
        for s in steps
        if s["card"]["code"] not in ("purchase", "salary")
    )


def valid(steps, config):
    return not submit_blockers(evaluate_expanded_scenario(steps, config))


def record(identity, steps, config, family=None, group=None, blind=False):
    values = canonical_expanded_steps(steps, config)
    snapshot = evaluate_expanded_scenario(values, config)
    blockers = submit_blockers(snapshot)
    if blockers:
        raise ValueError(f"{identity}: {blockers}")
    features = extract_features(values, config)
    result = dict(
        id=identity,
        group=group,
        family=family,
        steps=values,
        observable_hash=fingerprint(values, config),
        config_hash=digest(config),
        config_snapshot=deepcopy(config),
        features=features,
        resources=snapshot["resources_after"],
        totals=snapshot["totals"],
    )
    if not blind:
        score, explanation = label(features, rubric())
        result.update(
            target_risk_score=score,
            explanation=explanation,
            baseline=score_expanded_scenario(values, config),
            interpretation_limits=rubric()["limitations"],
        )
    return result


def build(seed=20260914):
    rng = random.Random(seed)
    config = demo_config()
    diagnostics = []
    cards = {c["code"]: c for c in config["card_snapshots"]}

    def make_inventory(count, cash, salary):
        from decimal import Decimal

        # Prescribed compositions, selected before scoring; total stays 400,000.
        credit_amounts = [70000, 70000, 60000] if salary else [80000, 80000, 70000]
        inventory = [("incoming_transfer", amount) for amount in credit_amounts]
        cents, remainder = divmod((400000 - cash) * 100, count)
        inventory += [
            ("card_transfer", Decimal(cents + (i < remainder)) / 100)
            for i in range(count)
        ]
        if cash:
            inventory.append(("cash_withdrawal", cash))
        if salary:
            inventory.append(("salary", 30000))
        return inventory

    def templates_for(count, cash, salary, needed, require_cash_link=False):
        inventory = make_inventory(count, cash, salary)
        found, seen = [], set()
        for attempt in range(20000):
            order = list(inventory)
            rng.shuffle(order)
            values = []
            for i, (code, amount) in enumerate(order):
                values.append(
                    dict(
                        step_id=str(UUID(int=i + 1)),
                        card={k: cards[code][k] for k in ("id", "code", "version")},
                        amount=str(amount),
                        context={},
                        action_details={"transfer_source": "domestic_bank"}
                        if code == "incoming_transfer"
                        else {},
                        sender_id="employer"
                        if code == "salary"
                        else "A"
                        if code == "incoming_transfer"
                        else None,
                        recipient_id="A" if code == "card_transfer" else None,
                        interval_minutes=None if i == 0 else 1,
                    )
                )
            signature = topology(values)
            if signature in seen:
                continue
            seen.add(signature)
            if require_cash_link and not any(
                a["card"]["code"] == "incoming_transfer"
                and b["card"]["code"] == "cash_withdrawal"
                for a, b in zip(values, values[1:])
            ):
                continue
            blockers = submit_blockers(evaluate_expanded_scenario(values, config))
            if blockers:
                diagnostics.append(
                    dict(
                        composition=[count, cash, salary],
                        attempt=attempt,
                        steps=values,
                        blockers=blockers,
                    )
                )
                continue
            found.append(values)
            if len(found) == needed:
                return found
        raise ValueError(
            str(
                (
                    len(found),
                    Counter(
                        b["reason"]
                        for d in diagnostics
                        if d["composition"] == [count, cash, salary]
                        for b in d["blockers"]
                    ),
                )
            )
        )

    # Similar compositions share parents even when authored in different families.
    compositions = [
        (5, 0, False),
        (6, 10000, False),
        (5, 30000, False),
        (8, 0, False),
        (5, 10000, False),
        (5, 0, True),
    ]
    groups = [
        "five-transfers",
        "six-transfers",
        "five-transfers",
        "eight-transfers",
        "five-transfers",
        "five-transfers",
    ]
    references = []
    for family, (count, cash, salary) in enumerate(compositions):
        template = templates_for(count, cash, salary, 1, require_cash_link=family == 2)[
            0
        ]
        for variant in range(8):
            values = deepcopy(template)
            party = ("A", "B", "C", "D")[variant % 4]
            credit_index = 0
            for i, value in enumerate(values):
                code = value["card"]["code"]
                if code == "incoming_transfer":
                    value["sender_id"] = party
                    if family == 4:
                        value["action_details"]["transfer_source"] = (
                            "payment_service",
                            "crypto_exchange",
                            "foreign_bank_kg",
                        )[credit_index]
                    credit_index += 1
                elif code == "card_transfer":
                    value["recipient_id"] = (
                        party if variant < 4 else ("A" if i % 2 else party)
                    )
            # Costs are checked against engine headroom, never against target scores.
            if variant % 4 == 0:
                for i in range(1, len(values)):
                    if values[i - 1]["card"]["code"] == "incoming_transfer":
                        trial = deepcopy(values)
                        trial[i]["interval_minutes"] = 60
                        if valid(trial, config):
                            values = trial
            if variant >= 4:
                purchase = demo_steps(config, "purchase")[-1]
                purchase["step_id"] = str(UUID(int=100))
                purchase["amount"] = str(1000 + variant * 100)
                # Reserve time for the extra operation; do not change game resources.
                while not valid(values + [purchase], config):
                    waits = [s for s in values if (s.get("interval_minutes") or 1) > 1]
                    if not waits:
                        raise ValueError("Purchase variant infeasible")
                    waits[-1]["interval_minutes"] = 1
                values.append(purchase)
            references.append(
                record(
                    f"R{family + 1}-{variant + 1}",
                    values,
                    config,
                    FAMILIES[family],
                    groups[family],
                )
            )
    # Seven-transfer compositions were reserved before rubric review and never
    # used for reference generation. All their permutations stay in one blind group.
    blind_templates = templates_for(7, 0, False, 3) + templates_for(7, 20000, False, 21)
    challenges = [
        record(
            f"B{i + 1:02}", values, config, group="blind-seven-transfers", blind=True
        )
        for i, values in enumerate(blind_templates)
    ]
    # Expectations fixed before evaluating modified chains; no best-score search.
    pairs = []
    original = demo_steps(config)
    for kind, expectation in [
        ("party", "increase"),
        ("interval", "decrease"),
        # Both versions retain intensive activity and now meet its same floor.
        ("order", "equal"),
        ("purchase", "decrease"),
        ("purchase_background", "decrease"),
        ("salary", "decrease"),
        ("source", "equal"),
    ]:
        changed = deepcopy(original)
        if kind == "party":
            for s in changed:
                if s.get("sender_id"):
                    s["sender_id"] = "C"
                if s.get("recipient_id"):
                    s["recipient_id"] = "C"
        elif kind == "interval":
            for i in (1, 4, 7):
                changed[i]["interval_minutes"] = 60
        elif kind == "order":
            changed[4], changed[5] = changed[5], changed[4]
        elif kind == "purchase":
            changed.append(demo_steps(config, "purchase")[-1])
        elif kind == "purchase_background":
            changed = []
            for i, step in enumerate(original):
                changed.append(deepcopy(step))
                if i in (1, 4, 8):
                    purchase = demo_steps(config, "purchase")[-1]
                    purchase["amount"] = "2000"
                    purchase["step_id"] = str(UUID(int=100 + i))
                    changed.append(purchase)
        elif kind == "salary":
            card = next(c for c in config["card_snapshots"] if c["code"] == "salary")
            changed.append(
                dict(
                    step_id=str(UUID(int=11)),
                    card={k: card[k] for k in ("id", "code", "version")},
                    amount=card["min_amount"],
                    context={},
                    action_details={},
                    sender_id="employer",
                    recipient_id=None,
                    interval_minutes=1,
                )
            )
        elif kind == "source":
            changed[0]["action_details"]["transfer_source"] = "crypto_exchange"
        pairs.append(
            dict(
                kind=kind,
                expectation=expectation,
                before=record(f"{kind}-before", original, config),
                after=record(f"{kind}-after", changed, config),
            )
        )
    from scripts.aml_dataset.review_contexts import enrich_review

    return enrich_review(
        dict(
            seed=seed,
            config=config,
            references=references,
            challenges=challenges,
            pairs=pairs,
            diagnostics=diagnostics,
        ),
        record,
        valid,
    )


def validate(package):
    config = package["config"]
    refs, blind = package["references"], package["challenges"]
    assert len(refs) == 48 and len(blind) == 24
    assert sorted(Counter(r["family"] for r in refs).values()) == [8] * 6
    hashes = set()
    collisions = defaultdict(list)
    for row in refs + blind:
        row_config = row["config_snapshot"]
        assert valid(row["steps"], row_config), row["id"]
        assert row["config_hash"] == digest(row_config)
        assert row["features"] == extract_features(row["steps"], row_config)
        assert row["observable_hash"] == fingerprint(row["steps"], row_config)
        snapshot = evaluate_expanded_scenario(row["steps"], row_config)
        assert (
            row["totals"] == snapshot["totals"]
            and row["resources"] == snapshot["resources_after"]
        )
        assert row["observable_hash"] not in hashes, "duplicate observable chain"
        hashes.add(row["observable_hash"])
        for value in row["features"].values():
            assert (
                isinstance(value, str)
                or isinstance(value, (int, float))
                and math.isfinite(value)
            )
        if row in refs:
            assert (
                row["group"]
                == {5: "five-transfers", 6: "six-transfers", 8: "eight-transfers"}[
                    row["features"]["count_card_transfer"]
                ]
            )
            score, explanation = label(row["features"], rubric())
            assert (
                row["target_risk_score"] == score and row["explanation"] == explanation
            )
            collisions[digest(row["features"])].append(row)
        else:
            assert (
                row["group"] == "blind-seven-transfers"
                and row["features"]["count_card_transfer"] == 7
            )
            assert (
                "target_risk_score" not in row
                and "baseline" not in row
                and "explanation" not in row
            )
    assert not {topology(r["steps"]) for r in refs} & {
        topology(r["steps"]) for r in blind
    }
    assert len({topology(r["steps"]) for r in blind}) == 24
    for rows in collisions.values():
        assert len({r["target_risk_score"] for r in rows}) == 1, (
            "feature/label conflict"
        )
    for pair in package["pairs"]:
        for side in ("before", "after"):
            row = pair[side]
            assert valid(row["steps"], row["config_snapshot"])
            assert row["features"] == extract_features(
                row["steps"], row["config_snapshot"]
            )
            assert row["target_risk_score"] == label(row["features"], rubric())[0]
        delta = pair["after"]["target_risk_score"] - pair["before"]["target_risk_score"]
        assert {"increase": delta > 0, "decrease": delta < 0, "equal": delta == 0}[
            pair["expectation"]
        ], (pair["kind"], delta)
    training = [r for r in refs if r["group"] == "five-transfers"]
    constants = sorted(
        k for k in refs[0]["features"] if len({r["features"][k] for r in training}) == 1
    )
    for diagnostic in package["diagnostics"]:
        assert diagnostic["blockers"] == submit_blockers(
            evaluate_expanded_scenario(diagnostic["steps"], config)
        )
        assert diagnostic["blockers"]
    scores = [r["target_risk_score"] for r in refs]
    assert len(set(scores)) > 1
    return dict(
        status="technical_review_passed_not_approved",
        references=48,
        blind=24,
        groups=len({r["group"] for r in refs}),
        independent_holdout_ready=False,
        holdout_parent_disjoint=True,
        coverage={
            k: sorted({r["features"][k] for r in refs})
            for k in (
                "num_steps",
                "count_card_transfer",
                "count_cash_withdrawal",
                "count_salary",
                "count_purchase",
                "interval_max",
                "income_basis",
                "history_known",
                "history_empty",
                "history_debit_mean",
                "night_share",
                "channel_web_count",
                "channel_branch_count",
            )
        },
        risk_min=min(scores),
        risk_max=max(scores),
        constant_features=constants,
        feature_collisions=[
            [r["id"] for r in rows] for rows in collisions.values() if len(rows) > 1
        ],
        diagnostics=len(package["diagnostics"]),
        pairs=len(package["pairs"]),
    )


def write_package(package, destination):
    report = validate(package)
    destination.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        (destination / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
        )

    write("config.json", package["config"])
    write("rubric.json", rubric())
    write("quality.json", report)
    (destination / "DATASET_CARD.md").write_text(f"""# Паспорт пакета кандидатов

Назначение: совместная проверка учебного риска 0–100; это не обучающий релиз.
Генератор {GENERATOR_VERSION}; extractor {FEATURE_VERSION}; seed {package["seed"]}.
Рубрика {rubric()["version"]}: {rubric()["status"]}. Объём: 48 кандидатов, 24 слепые цепочки, {len(package["pairs"])} пар.

Каждая основная запись включает config_snapshot и проходит условия отправки при обороте 400 000 руб.
Ресурсы 180 000 руб., 30 времени и 30 энергии сохранены. История фиксирована до начала раунда
и не расходует его ресурсы. Каталог и профиль одинаковы для участников одного синтетического раунда.

Разбиение 32/8/8 по трём группам родства; слепая группа отдельная. Константы определяются только
по обучающим родителям. ID, seed, семейство, baseline, объяснения, нарушения и результат цели
не входят в CSV модели. Цель хранится отдельной колонкой target_risk_score.

Ограничения: три группы недостаточны для устойчивых выводов о качестве модели. Увеличение числа
вариаций не создаёт новые независимые группы. Текст профиля доступен для ручного просмотра,
но не используется как ID-категория или скрытая экспертная оценка. Качество реального банковского
AML этим набором не подтверждается. CatBoost не обучался. См. quality.json и DECISIONS.md.
""")
    write(
        "manifest.json",
        dict(
            generator=GENERATOR_VERSION,
            extractor=FEATURE_VERSION,
            seed=package["seed"],
            config_hash=digest(package["config"]),
            rubric_hash=digest(rubric()),
            package_hash=digest(package),
            status="pending_joint_review",
            mass_generation_enabled=False,
        ),
    )
    for key in ("references", "challenges", "pairs", "diagnostics"):
        (destination / f"{key}.jsonl").write_text(
            "".join(stable(row) + "\n" for row in package[key])
        )
    columns = [
        k
        for k in package["references"][0]["features"]
        if k not in report["constant_features"]
    ]
    write(
        "feature-schema.json",
        dict(
            version=FEATURE_VERSION,
            columns=columns,
            excluded_constants=report["constant_features"],
            selection_basis="training parents only; validation/blind excluded from feature selection; provisional",
        ),
    )
    with (destination / "features.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns + ["target_risk_score"])
        writer.writeheader()
        writer.writerows(
            {
                **{k: r["features"][k] for k in columns},
                "target_risk_score": r["target_risk_score"],
            }
            for r in package["references"]
        )
    # Related five-transfer compositions (including salary and cash variants) stay together.
    with (destination / "split.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["row_index", "id", "group", "split"])
        for i, r in enumerate(package["references"]):
            writer.writerow(
                [
                    i,
                    r["id"],
                    r["group"],
                    {
                        "five-transfers": "train",
                        "six-transfers": "validation",
                        "eight-transfers": "test",
                    }[r["group"]],
                ]
            )
    rows = [
        "# Кандидаты для совместной проверки",
        "",
        "Статус: черновик. Эти оценки ещё не согласованы; массовая генерация отключена.",
        "",
        "Шаги и наблюдения: references.jsonl. Слепые цепочки без оценок: challenges.jsonl.",
        "",
        "| ID | Семейство | Балл | Оборот | Покупки |",
        "|---|---|---:|---:|---:|",
    ]
    for r in package["references"]:
        rows.append(
            f"| {r['id']} | {r['family']} | {r['target_risk_score']} | {r['totals']['target_outflow']} | {r['totals']['purchase_outflow']} |"
        )
    rows += [
        "",
        "## Пары",
        "",
        "| Изменение | Ожидание | До | После |",
        "|---|---|---:|---:|",
    ]
    for pair in package["pairs"]:
        rows.append(
            f"| {pair['kind']} | {pair['expectation']} | {pair['before']['target_risk_score']} | {pair['after']['target_risk_score']} |"
        )
    rows += [
        "",
        "## Ограничения",
        "",
        "У каждой цепочки свой config_snapshot: известная, пустая либо неизвестная предыстория, разные исторические списания, дневное/ночное начало. Покрыты интервалы 1/10/60/1440 и каналы. Профиль общий и фиксирован внутри каждого синтетического раунда. Названия семейств не участвуют в оценке.",
        "",
        "Разбиение кандидатов 32/8/8: родственные шаблоны с пятью переводами объединены, варианты с шестью и восемью выделены целиком. Всего три группы, поэтому это предварительное разбиение, а не основание для выводов о модели. 24 слепые цепочки имеют семь переводов — состав, не используемый в кандидатах. Все они остаются в отдельной группе; независимая ручная разметка ещё не выполнена.",
        "",
        "Эффект времени ограничен согласованными 15% относительно той же последовательности с минутными интервалами. Пороги 10/60 минут согласованы. Правила эпизодов и совместных ограничений: docs/verification/aml-rubric-consolidated-review.md. Это учебный риск.",
        "",
        "Все признаки остаются доступны extractor; константы исключены по обучающим родителям, без validation/test/blind. Всего три группы кандидатов — ограничение будущей проверки модели. Для следующего шага нужен совместный разбор рубрики и кандидатов; см. DECISIONS.md.",
    ]
    (destination / "REVIEW.md").write_text("\n".join(rows) + "\n")
    for key, filename in [("references", "CHAINS.md"), ("challenges", "BLIND.md")]:
        lines = [
            "# Цепочки для разбора",
            "",
            "Общий профиль и каталог: [снимок конфигурации](config.json).",
            "",
        ]
        for row in package[key]:
            behavior = row["config_snapshot"]["behavior"]
            history = behavior["history"]["operations"]
            lines += [
                f"## {row['id']}",
                "",
                f"Начало: {behavior['timeline']['starts_at']}. Профиль: {behavior['profile']['description']}",
                f"История: {'неизвестна' if history is None else 'наблюдаемых операций: ' + str(len(history))}.",
                "",
                "| Дата истории | Операция | Сумма | Сторона |",
                "|---|---|---:|---|",
                *[
                    f"| {e['occurred_at']} | {e['operation_code']} | {e['amount']} | {e.get('counterparty_id') or '—'} |"
                    for e in history or []
                ],
                "",
                "| Шаг | Карточка | Сумма | Сторона | Интервал, мин | Детали |",
                "|---:|---|---:|---|---:|---|",
            ]
            for i, step in enumerate(row["steps"], 1):
                lines.append(
                    f"| {i} | {step['card']['code']} | {step['amount']} | {step.get('sender_id') or step.get('recipient_id') or '—'} | {step.get('interval_minutes') or 'начало'} | {stable(step['action_details'])} |"
                )
            if key == "references":
                lines += [
                    "",
                    f"Предложенная оценка: **{row['target_risk_score']}**.",
                    "",
                ]
                for term in row["explanation"]:
                    lines.append(
                        f"- {term['name']}: {term['contribution']} балла; сигнал {term['signal']:.4f}, взаимодействие {term['interaction']:.4f}."
                    )
            else:
                lines += ["", "Независимая оценка: __. Обоснование: __.", ""]
            lines += [
                "",
                "Ограничение: соседство операций не доказывает источник списанных средств; оценка учебная.",
                "",
            ]
        (destination / filename).write_text("\n".join(lines) + "\n")
    from scripts.aml_dataset.joint_review import prepare_forms

    prepare_forms(
        package, destination, json.loads((destination / "manifest.json").read_text())
    )
    review_lines = [
        "# Решение перед пилотом",
        "",
        "Учтены замечания пользователя: всплеск после затишья, объём и регулярность потока, отсутствие фона, сильный эффект дорогой зарплаты.",
        "",
        "Численные коэффициенты ниже предложены для согласования. Решения пользователя по всем 48 оценкам ещё не заполнены.",
        "",
        "[48 кандидатов с наблюдениями](CHAINS.md) · [24 слепые цепочки](BLIND.md) · [Рубрика](rubric.json)",
        "",
        "| Вклад | Максимальный вес |",
        "|---|---:|",
    ]
    review_lines.extend(
        f"| {term['name']} | {term['weight']} |" for term in rubric()["terms"]
    )
    review_lines += [
        "",
        "Объём, число списаний и число переходов credit→debit определяют силу транзитного сочетания независимо от пауз. Масштабы записаны в activity_scaling рубрики; 400 000 руб. — игровая цель, не банковский порог.",
        "",
        "После наблюдаемой пустой истории добавляется вклад за всплеск. Неизвестная история получает отдельный вклад неопределённости до 22 вместе с транзитом; она не считается пустой и не получает надбавку за затишье. Фон пока определяется по историческим зарплатам и покупкам; сегодняшняя мелкая покупка не стирает цепочку.",
        "",
        "Предложение для текущей зарплаты: реестр снижает сумму вкладов на 25%, договор услуг — на 20%, отсутствие назначения — на 0%. Снижение применяется один раз. Коэффициенты и различие оснований требуют согласования.",
        "Текущие покупки, включая одиночную, дают единый небольшой эффект: максимум 3 балла × min(количество/3, 1) × min(доля расходов/5%, 1). Второй скидки внутри транзита нет. Три покупки по 2000 руб. при обороте 400000 дают 0.9 балла до эффекта времени.",
        "",
        "Зарплата с реестром уже стоит 8 энергии и 9 времени. В контрольной цепочке после неё остаётся по одной единице обоих ресурсов. Новые затраты в игру не внесены.",
        "",
        "Решения можно обсудить в чате и затем перенести в reference-decisions.csv и review-decision.json. Подтверждение принципов не означает согласования всех коэффициентов и 48 оценок.",
        "",
        "Для слепых цепочек нужны независимые баллы и объяснения в blind-decisions.csv; их не вычисляем этой же рубрикой.",
        "",
        "Далее: согласование кандидатов → пилот 2 000 → совместный разбор 120 и слепых цепочек → выпуск до 20 000. Этап 08 пока не начинается.",
    ]
    (destination / "DECISIONS.md").write_text("\n".join(review_lines) + "\n")
    return report
