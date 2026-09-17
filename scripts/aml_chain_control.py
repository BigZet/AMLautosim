"""Separately authored control chains; no use of the population generator.

These are authored economic outcomes, not independent expert adjudication.
Freeze before model evaluation; never use this control pack to train a model.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import csv_bytes, FEATURE_NAMES
from scripts.audit_aml_history_population import file_hash, require
from scripts.build_aml_fixed_history_dataset import common_context, private_ledger

# I = incoming, T = card transfer, W = cash, S = salary, P = purchase.
# Each sequence is authored directly, not sampled from class-specific rules.
SEQUENCES = {
    "staged": "T:B:78000 T:C:77000 I:A:78000 T:D:65000 I:B:77000 T:C:60000 I:D:79000 T:A:60000 T:B:60000",
    "relay": "I:A:80000 T:B:79000 T:C:71000 I:D:79000 T:B:65000 T:A:75000 I:C:78000 T:D:60000 T:B:50000",
    "split": "T:B:50000 T:C:50000 I:A:80000 T:D:50000 T:A:50000 I:B:80000 T:C:50000 T:D:50000 I:C:80000 T:A:50000 T:B:50000",
    "cash_first": "W:-:60000 T:B:70000 I:A:80000 T:C:70000 I:B:80000 W:-:60000 T:D:70000 I:C:80000 T:A:70000",
    "cash_relay": "I:A:80000 W:-:60000 T:B:70000 I:B:80000 T:C:70000 W:-:60000 I:C:80000 T:D:70000 T:A:70000",
    "consolidate": "I:B:80000 I:C:78000 T:A:70000 T:A:60000 P:shop:1200 T:A:70000 T:A:60000 I:D:79000 T:A:70000 T:A:70000",
    "refund": "I:A:80000 T:A:80000 T:B:75000 I:C:78000 T:D:55000 T:B:65000 I:D:79000 T:C:60000 T:B:65000",
    "reserve": "T:B:70000 T:C:60000 I:A:80000 T:D:70000 I:B:80000 T:A:60000 T:C:70000 I:D:80000 T:B:70000",
    "household": "S:employer:25000 T:B:80000 T:C:80000 I:A:80000 P:shop:3000 T:D:80000 I:B:80000 T:A:80000 I:C:80000 T:B:80000",
    "mixed_relay": "S:employer:25000 I:A:80000 T:B:80000 T:C:80000 I:B:80000 P:shop:3000 T:D:80000 I:C:80000 T:A:80000 T:B:80000",
    "uneven": "I:A:78000 T:B:73000 T:C:47000 I:D:79000 T:A:79000 T:B:51000 I:C:80000 T:D:77000 T:A:73000",
    "batched": "T:B:77000 I:A:78000 T:C:63000 T:D:71000 I:B:79000 T:A:54000 T:C:65000 I:D:80000 T:B:70000",
}

# title, sequence, waits, outcome, substantive private event; no feature-derived labels.
CASES = [
    (
        "Ремонт по этапам",
        "staged",
        {2: 60, 5: 60},
        0,
        "Владелец оплатил принятые этапы ремонта из накоплений; поступления погашают настоящие долги родственников за их долю расходов.",
    ),
    (
        "Срочная оплата переезда",
        "relay",
        {},
        0,
        "Три участника оплатили свою долю переезда; владелец немедленно рассчитался с исполнителями по действительным обязательствам.",
    ),
    (
        "Равные возмещения расходов",
        "split",
        {3: 10},
        0,
        "Восемь равных платежей погашают ранее согласованные личные обязательства. Равенство сумм не связано с обходом контроля.",
    ),
    (
        "Наличные для ремонта",
        "cash_first",
        {3: 60},
        0,
        "Наличные заранее выделены на материалы и оплату работ; последующие поступления возмещают часть личных расходов.",
    ),
    (
        "Срочный наличный расчёт",
        "cash_relay",
        {},
        0,
        "Наличные требуются для фактически состоявшейся покупки подержанного имущества; перечисления остальных участников законны.",
    ),
    (
        "Возврат займа одному кредитору",
        "consolidate",
        {4: 60},
        0,
        "Платежи одному кредитору погашают реальный личный заём. Поступления принадлежат владельцу счёта на законном основании.",
    ),
    (
        "Исправление переплаты",
        "refund",
        {},
        0,
        "Первое зачисление является ошибочной переплатой и возвращено плательщику; остальные выплаты относятся к отдельным настоящим обязательствам.",
    ),
    (
        "Расчёты из накоплений",
        "reserve",
        {2: 10, 5: 10},
        0,
        "Платежи начаты до поступлений из собственных накоплений, затем продолжаются расчёты по фактическим личным обязательствам.",
    ),
    (
        "Зарплата и домашние расходы",
        "household",
        {},
        0,
        "Зарплата и поступления законны; покупка состоялась, остальные платежи погашают личные долги.",
    ),
    (
        "Неравные платежи за имущество",
        "uneven",
        {3: 10},
        0,
        "Разные суммы соответствуют самостоятельным договорам приобретения личного имущества; чужие средства не присваивались.",
    ),
    (
        "Передача присвоенного через счёт",
        "relay",
        {},
        1,
        "Отправитель первого поступления присвоил доверенный ему залог. Владелец счёта получил указание переслать деньги номинальным получателям.",
    ),
    (
        "Сокрытие среди равных платежей",
        "split",
        {},
        1,
        "Первое поступление содержит присвоенный залог; равные выплаты выполняют распоряжение контролёра о распределении средств, а заявленные долги вымышлены.",
    ),
    (
        "Конвертация присвоенного в наличные",
        "cash_relay",
        {},
        1,
        "Первый перевод получен после присвоения доверенных денег; наличные после зачисления передаются контролёру, а не продавцу имущества.",
    ),
    (
        "Консолидация у контролёра",
        "consolidate",
        {},
        1,
        "Первый отправитель отвёл доверенные деньги; платежи одному получателю передают их контролёру под видом возврата несуществующего займа.",
    ),
    (
        "Возврат под видом исправления",
        "refund",
        {},
        1,
        "Первый перевод содержит присвоенные средства; обратный платёж согласован для сокрытия их движения, фактической переплаты не было.",
    ),
    (
        "Подготовленное сокрытие с ожиданием",
        "staged",
        {2: 60, 5: 60},
        1,
        "До присвоенного поступления используются собственные накопления; дальнейшие платежи распоряжаются чужими деньгами. Ожидание не делает исход законным.",
    ),
    (
        "Наличные до и после присвоения",
        "cash_first",
        {3: 60},
        1,
        "Первый наличный резерв законен; первое входящее содержит присвоенное, часть последующих выплат и снятия передаётся контролёру.",
    ),
    (
        "Бытовые операции как прикрытие",
        "mixed_relay",
        {},
        1,
        "Зарплата и покупка настоящие, но первый сторонний перевод присвоен отправителем; последующие переводы направляют его номинальным получателям.",
    ),
    (
        "Неравные выплаты номиналам",
        "uneven",
        {},
        1,
        "Первое поступление содержит присвоенное; суммы выплат различаются по инструкции контролёра, реальные договоры личных покупок отсутствуют.",
    ),
    (
        "Рассредоточенные расчёты прикрытия",
        "batched",
        {3: 10, 6: 60},
        1,
        "Первый сторонний перевод происходит из присвоения. Чередование с расходованием личных накоплений скрывает распоряжение чужими средствами.",
    ),
]


def steps_for(name, waits, identity):
    codes = {
        "I": (2, "incoming_transfer"),
        "T": (3, "card_transfer"),
        "W": (4, "cash_withdrawal"),
        "S": (1, "salary"),
        "P": (5, "purchase"),
    }
    steps = []
    for n, token in enumerate(SEQUENCES[name].split(), 1):
        kind, party, amount = token.split(":")
        card_id, code = codes[kind]
        step = dict(
            step_id=str(uuid5(NAMESPACE_URL, f"{identity}/{n}")),
            card=dict(id=card_id, code=code, version=1),
            amount=amount,
            context={},
            action_details={},
            interval_minutes=None if n == 1 else waits.get(n, 1),
            purpose_code="shared_expense",
        )
        if kind == "I":
            step.update(
                sender_id=party,
                action_details=dict(incoming_kind="bank_transfer", bank_country="RU"),
            )
        elif kind == "T":
            step.update(recipient_id=party, context=dict(channel="mobile"))
        elif kind == "W":
            step.update(context=dict(channel="atm"), purpose_code="personal_spending")
        elif kind == "S":
            step.update(
                sender_id="employer",
                action_details=dict(income_basis="payroll_registry"),
                purpose_code="salary",
            )
        else:
            step.update(recipient_id="shop", purpose_code="personal_spending")
        steps.append(step)
    return steps


def controls():
    context, _ = common_context()
    rows = []
    specifications = [
        *CASES,
        *[
            (
                "Неизвестное основание: " + name,
                name,
                {},
                None,
                "Происхождение средств и действительность обязательств не установлены.",
            )
            for name in ("relay", "cash_relay", "refund", "consolidate", "mixed_relay")
        ],
    ]
    for n, (title, name, waits, outcome, explanation) in enumerate(specifications, 1):
        sid = f"control-{n:02d}"
        steps = steps_for(name, waits, sid)
        truth = (
            private_ledger(
                steps,
                "criminal_proceeds_concealment"
                if outcome == 1
                else "lawful_personal_settlement",
            )
            if outcome is not None
            else dict(aml_episode_present=None)
        )
        truth["economic_event"] = explanation
        rows.append(
            dict(
                scenario_id=sid,
                title=title,
                provenance_group_id=f"control-recipe-{name}",
                family_id="P05"
                if "cash" in name
                else "P10"
                if "mixed" in name or name == "household"
                else "P06",
                aml_label=outcome,
                label_status="confirmed" if outcome is not None else "unresolved",
                review_status="authored_unreviewed",
                review=None,
                author_id="manual-chain-control-v1",
                label_source="separately-authored-economic-event",
                label_protocol_version="aml-labels-v1",
                population_id="aml-game-balanced-v1",
                label_rationale=explanation,
                author_truth=truth,
                public_snapshot=dict(config=context, steps=steps),
                observability=dict(
                    distinguishable=False,
                    reason="Private ownership is not proved by transaction shape. Contrary outcomes and unresolved cases are deliberate controls.",
                ),
                hypothesis_source=dict(
                    kind="separately authored control recipe, no population sampler"
                ),
                alternative_explanation=dict(
                    description="The same behavior may implement real obligations or conceal diverted proceeds."
                ),
                necessary_facts=[
                    "source ownership",
                    "payment authorization",
                    "actual obligations",
                ],
                forbidden_information=[
                    "title",
                    "author_truth",
                    "aml_label",
                    "scenario_id",
                ],
                provenance=dict(root_id=f"control-recipe-{name}", parent_ids=[]),
            )
        )
    return rows


def freeze(output):
    output = Path(output)
    require(not output.exists(), "Control output already exists")
    rows = controls()
    features = p.validate_sources(rows, p.protocol())
    output.mkdir(parents=True)
    (output / "casebook.jsonl").write_bytes(p.jsonl_bytes(rows))
    (output / "features.csv").write_bytes(
        csv_bytes(
            ["scenario_id", *FEATURE_NAMES],
            [dict(scenario_id=sid, **v) for sid, v in features.items()],
        )
    )
    report = dict(
        rows=len(rows),
        labels=dict(Counter(str(r["aml_label"]) for r in rows)),
        context_sha256=p.digest(rows[0]["public_snapshot"]["config"]),
        purpose="held-out control only; never fit or calibrate on these cases",
        independently_authored_recipes=True,
        independent_domain_review=False,
        release_ready=False,
        source_sha256=file_hash(__file__),
        artifact_hashes={
            name: file_hash(output / name)
            for name in ("casebook.jsonl", "features.csv")
        },
    )
    (output / "freeze.json").write_bytes(p.json_bytes(report))
    text = [
        "# Контрольные цепочки",
        "",
        "10 законных авторских исходов, 10 незаконных и 5 неустановленных. Составлены отдельно от генератора; не являются независимой экспертной разметкой. Не использовать для обучения.",
        "",
    ]
    for row in rows:
        text.extend(
            [
                f"## {row['scenario_id']}: {row['title']}",
                "",
                f"Метка: {row['aml_label']}. {row['label_rationale']}",
                "",
                "| № | Операция | Сумма | Сторона | Интервал |",
                "|---|---|---:|---|---:|",
            ]
        )
        for n, step in enumerate(row["public_snapshot"]["steps"], 1):
            text.append(
                f"| {n} | {step['card']['code']} | {step['amount']} | {step.get('sender_id', step.get('recipient_id', 'cash'))} | {step['interval_minutes']} |"
            )
        text.append("")
    (output / "README.md").write_text("\n".join(text), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(freeze(parser.parse_args().output)))
