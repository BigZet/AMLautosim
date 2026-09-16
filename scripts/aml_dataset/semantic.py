"""V9 rubric review only. Mass generation is gated by an explicit reviewed hash."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from scripts.aml_dataset.expanded import label as old_label
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import (
    extract_features as old_features,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v4 import extract_features
from src.aml_workshop_simulator.services.semantic_contract import new_config, evaluate


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def proposed_rubric():
    rules = json.loads(Path("config/synthetic_dataset/v2/rubric.json").read_text())
    rules["version"] = "educational-risk-v3-review-1"
    rules["status"] = "awaiting-eight-case-review"
    rules["intensive_activity"]["floor"] = 0
    rules["limitations"] = [
        text for text in rules["limitations"] if "нижняя опора 45" not in text
    ] + ["V9: принудительное доведение до 45 удалено; отдельный вклад интенсивности до 10 и его затухание сохранены."]
    rules["notes"] = [
        "V9: no forced intensity floor; capped intensity contribution and all other numerical policies unchanged."
    ]
    for term in rules["terms"]:
        if term["name"] == "Транзит без наблюдаемой фоновой активности":
            term["name"] = "Недостаточная фоновая активность"
    return rules


def require_review(approval, rules, rows):
    if (
        approval.get("status") != "approved"
        or approval.get("rubric_sha256") != digest(rules)
        or approval.get("cases_sha256") != digest(rows)
    ):
        raise ValueError(
            "Массовая разметка v9 ожидает согласования восьми примеров и их контрольных сумм"
        )


def review_cases():
    fixture = json.loads(
        Path("docs/verification/semantic-interface-audit/fixtures.json").read_text()
    )
    old_config = fixture["config"]
    old_rules = json.loads(Path("config/synthetic_dataset/v2/rubric.json").read_text())
    rules = proposed_rubric()
    rows = []
    cases = [
        ("Опора интенсивности", 1, "floor"),
        ("Концентрация и наличные", 4, "concentration"),
        ("Зарплата по реестру", 10, "salary"),
        ("Недостаточный фон", 1, "background"),
        ("Наблюдаемое отсутствие истории", 1, "history"),
        ("Вывод с биржи", 1, "exchange"),
        ("Продажа активов P2P", 1, "p2p"),
        ("Перевод через посредника", 1, "service"),
    ]
    for title, number, variant in cases:
        source = deepcopy(
            next(s["steps"] for s in fixture["strategies"] if s["number"] == number)
        )
        previous = deepcopy(old_config)
        config = new_config(old_config)
        if variant == "background":
            for c in (previous, config):
                c["behavior"]["history"]["operations"] = [
                    e
                    for e in c["behavior"]["history"]["operations"]
                    if e["operation_code"] != "purchase"
                ]
        if variant == "history":
            for c in (previous, config):
                c["behavior"]["history"]["operations"] = []
        steps = deepcopy(source)
        for step in steps:
            if step["card"]["code"] == "incoming_transfer":
                step["action_details"] = {
                    "incoming_kind": "bank_transfer",
                    "bank_country": "RU",
                }
        incoming = next(s for s in steps if s["card"]["code"] == "incoming_transfer")
        if variant in ("exchange", "p2p", "service"):
            incoming["action_details"] = {
                "incoming_kind": {
                    "exchange": "exchange_withdrawal",
                    "p2p": "crypto_p2p",
                    "service": "payment_service",
                }[variant]
            }
            if variant == "exchange":
                incoming["sender_id"] = "exchange"
        blockers = submit_blockers(evaluate(steps, config))
        if blockers:
            raise ValueError((title, blockers))
        features = extract_features(steps, config)
        target, terms = old_label(features, rules)
        comparable = variant not in ("exchange", "p2p")
        if variant == "service":
            next(s for s in source if s["card"]["code"] == "incoming_transfer")[
                "action_details"
            ] = {"transfer_source": "payment_service"}
        before = (
            old_label(old_features(source, previous), old_rules)[0]
            if comparable
            else None
        )
        rows.append(
            dict(
                number=len(rows) + 1,
                title=title,
                variant=variant,
                old_score=before,
                proposed_score=target,
                change=None if before is None else round(target - before, 4),
                comparison="same observable scenario"
                if comparable
                else "new meaning; no forced legacy label",
                config=config,
                steps=steps,
                features=features,
                explanation=terms,
            )
        )
    return rules, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rules, rows = review_cases()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in [
        ("rubric.json", rules),
        ("cases.json", rows),
        (
            "review-status.json",
            dict(
                status="pending", rubric_sha256=digest(rules), cases_sha256=digest(rows)
            ),
        ),
    ]:
        (args.output / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        )
    table = [
        "# Восемь примеров: согласование рубрики v9",
        "",
        "Это оценки учебной рубрики, не прогноз новой модели. Массовая генерация и обучение не запускались.",
        "",
        "| № | Случай | Прежняя оценка | Новая оценка | Изменение |",
        "|---|---|---:|---:|---:|",
    ]
    for row in rows:
        table.append(
            f"| {row['number']} | {row['title']} | {row['old_score'] if row['old_score'] is not None else 'Не сопоставляется'} | {row['proposed_score']} | {row['change'] if row['change'] is not None else '—'} |"
        )
    table += [
        "",
        "Все восемь цепочек проходят движок и достигают цели. Для новых смыслов биржи и P2P прежняя оценка намеренно не вычисляется.",
        "",
        "Полные цепочки, снимки и разложение оценок: [cases.json](cases.json). Статус согласования: [review-status.json](review-status.json).",
    ]
    (args.output / "README.md").write_text("\n".join(table) + "\n")
    print("\n".join(table))


if __name__ == "__main__":
    main()
