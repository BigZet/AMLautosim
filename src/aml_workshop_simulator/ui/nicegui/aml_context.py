"""Read-only public evidence and explicit participant explanations for v10."""

from datetime import datetime
from decimal import Decimal

from nicegui import ui
from .counterparties import party_name
from src.aml_workshop_simulator.domain.operation_purposes import (
    allowed_purposes,
    purpose_field_label,
)

FACT_TYPES = {
    "source_of_funds": "Источник средств",
    "payment_purpose": "Основание платежа",
    "relationship": "Связь со стороной",
    "opening_balance": "Начальный остаток",
}
STATUSES = {
    "verified": "Подтверждено",
    "unverified": "Не проверено",
    "contradicted": "Выявлено противоречие",
    "unknown": "Статус неизвестен",
}
PROVENANCE = {
    "scenario_record": "Запись учебного сценария",
    "customer_statement": "Заявление клиента",
    "independent_record": "Независимая запись",
}
OPERATIONS = {
    "salary": "Зарплата",
    "incoming_transfer": "Входящий перевод",
    "card_transfer": "Перевод на карту",
    "cash_withdrawal": "Снятие наличных",
    "purchase": "Покупка",
}


def purpose_options(config, step=None):
    translations = {
        "unknown": "Не указано",
        "loan": "Заём",
        "refund": "Возврат средств",
        "asset_sale": "Продажа имущества",
        "shared_expense": "Совместные расходы",
        "service_payment": "Оплата услуг",
        "salary": "Зарплата",
        "personal_spending": "Личные расходы",
    }
    options = {
        p["code"]: (
            translations.get(p["code"], p["title"])
            if p["title"] in (p["code"], p["code"].replace("_", " "))
            else p["title"]
        )
        for p in config["behavior"]["aml_context"]["purpose_catalog"]
    }
    if step is not None:
        options = {
            key: value
            for key, value in options.items()
            if key in allowed_purposes(step)
        }
        if step["card"]["code"] == "card_transfer" and "asset_sale" in options:
            options["asset_sale"] = "Оплата приобретённого имущества"
        if step.get("action_details", {}).get("incoming_kind") == "exchange_withdrawal":
            if "unknown" in options:
                options["unknown"] = "Основание выводимых средств не уточнено"
    return options


def money(value):
    if value is None:
        return "неизвестно"
    return f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def moment(value):
    if value is None:
        return "неизвестно"
    date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    offset = date.strftime("%z")
    return date.strftime("%d.%m.%Y, %H:%M:%S") + f" UTC{offset[:3]}:{offset[3:]}"


def fact_title(fact, purposes):
    return f"{fact['id']} · {FACT_TYPES[fact['fact_type']]} · {purposes[fact['purpose_code']]} · {STATUSES[fact['verification_status']]}"


def fact_details(config, fact):
    parties = {p["id"]: party_name(p) for p in config["behavior"]["counterparties"]}
    return [
        f"Источник сведений: {PROVENANCE[fact['provenance']]}",
        f"Доступно с: {moment(fact['available_at'])}",
        f"Действует: {moment(fact['valid_from'])} — {moment(fact['valid_to'])}",
        "Стороны: "
        + (
            ", ".join(parties[p] for p in fact["counterparty_ids"])
            or "Без указанной стороны"
        ),
        "Операции: "
        + (
            ", ".join(OPERATIONS[c] for c in fact["operation_codes"])
            or "Начальный остаток"
        ),
        f"Предел покрытия поступлений: {money(fact['max_credit_amount'])}",
        f"Предел покрытия списаний: {money(fact['max_debit_amount'])}",
    ]


def context_panel(config):
    if config.get("schema_version") != 10:
        return
    ctx = config["behavior"]["aml_context"]
    purposes = purpose_options(config)
    with ui.expansion("Сведения и основания операций").classes("w-full"):
        if not any(f["fact_type"] != "opening_balance" for f in ctx["facts"]):
            ui.label(
                "В этой игре доступно подтверждение начального остатка. Документы по отдельным операциям не предоставлены; назначение является заявлением участника."
            ).classes("text-sm muted")
        ui.label(f"Сведения на: {moment(ctx['as_of'])}").classes("text-sm muted")
        ui.label("Ожидаемая активность").classes("font-semibold")
        expected = ctx["expected_activity"]
        ui.label(
            f"Период: {moment(expected['period_start'])} — {moment(expected['period_end'])}"
        )
        ui.label(
            "Виды деятельности: "
            + ", ".join(purposes[k] for k in expected["activity_kinds"])
        )
        for direction, label in (("credit", "Поступления"), ("debit", "Списания")):
            lo, hi = (
                expected[f"expected_{direction}_min"],
                expected[f"expected_{direction}_max"],
            )
            ui.label(
                f"{label}: "
                + ("неизвестно" if lo is None else f"{money(lo)} — {money(hi)}")
            )
        ui.label(
            "Это ожидаемые объёмы за указанный период, а не обязательные лимиты операций."
        ).classes("text-xs muted")
        coverage = {
            "complete": "Полная",
            "partial": "Частичная",
            "unknown": "Неизвестна",
        }
        ui.label("Полнота истории: " + coverage[ctx["history_coverage"]])
        if ctx["history_coverage"] != "unknown":
            ui.label(
                f"Известное окно истории: {moment(ctx['history_start'])} — {moment(ctx['history_end'])}"
            )
        ui.label(
            "Факты зафиксированы в раунде. Выбор основания не изменяет его проверку; учитываются срок, стороны, операция и предел суммы."
        ).classes("text-xs muted")
        if not ctx["facts"]:
            ui.label("Основания не представлены")
        for fact in ctx["facts"]:
            with ui.expansion(fact_title(fact, purposes)).classes("w-full"):
                for line in fact_details(config, fact):
                    ui.label(line).classes("text-sm")


def claim_details(config, claim_id):
    fact = next(
        (f for f in config["behavior"]["aml_context"]["facts"] if f["id"] == claim_id),
        None,
    )
    if fact is None:
        return "Основание не выбрано"
    return " · ".join(
        [fact_title(fact, purpose_options(config)), *fact_details(config, fact)]
    )


def explanation_selector(config, step, on_change):
    if config.get("schema_version") != 10:
        return
    purposes = purpose_options(config, step)
    valid = step.get("purpose_code") in purposes
    if len(purposes) == 1:
        if not valid:
            on_change("purpose_code", next(iter(purposes)))
        ui.label(
            f"{purpose_field_label(step)}: {next(iter(purposes.values()))}"
        ).classes("text-sm muted")
    else:
        issue = None

        def choose_purpose(event):
            on_change("purpose_code", event.value)
            if issue is not None:
                issue.set_visibility(event.value not in purposes)

        ui.select(
            purposes,
            value=step.get("purpose_code") if valid else None,
            label=purpose_field_label(step),
            on_change=choose_purpose,
        ).props("outlined dense options-dense").classes("operation-parameter")
        if not valid:
            issue = ui.label(
                "Прежнее назначение несовместимо с операцией. Выберите новое."
            ).classes("text-sm text-negative")
    # Include mismatched known facts: applicability is an observation resolved by the server.
    claims = {
        f["id"]: fact_title(f, purpose_options(config))
        for f in config["behavior"]["aml_context"]["facts"]
        if f["fact_type"] != "opening_balance"
    }
    if not claims:
        return
    details = ui.label(claim_details(config, step.get("claim_id"))).classes(
        "text-xs muted"
    )

    def update(event):
        on_change("claim_id", event.value)
        details.set_text(claim_details(config, event.value))

    ui.select(
        claims,
        value=step.get("claim_id"),
        label="Основание (необязательно)",
        on_change=update,
        clearable=True,
    ).props("outlined dense options-dense").classes("operation-parameter")


def explanation_readonly(config, step):
    if config.get("schema_version") != 10:
        return
    ui.label(
        purpose_field_label(step)
        + ": "
        + purpose_options(config, step).get(
            step.get("purpose_code"),
            purpose_options(config).get(step.get("purpose_code"), "Не указано"),
        )
    ).classes("text-sm muted")
    ui.label(claim_details(config, step.get("claim_id"))).classes("text-xs muted")
