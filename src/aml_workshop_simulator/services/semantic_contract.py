"""V9 observations and a private resource-only projection onto frozen v8 rules.

The projection is not a scoring fallback. V9 cannot use the v8 model.
"""

from copy import deepcopy
from typing import Literal

from pydantic import Field, model_validator

from src.aml_workshop_simulator.schemas.expanded_contract import (
    ExpandedBehavior,
    HistoricalOperation,
    History,
)

INCOMING_KINDS = {
    "bank_transfer": "Банковский перевод",
    "payment_service": "Перевод через платёжный сервис",
    "exchange_withdrawal": "Вывод с криптобиржи",
    "crypto_p2p": "Продажа криптоактивов P2P",
}
BANK_COUNTRIES = {"RU": "Российский банк", "KG": "Банк Кыргызстана"}


def fields_for(code):
    def field(key, title, options, default):
        return dict(
            key=key,
            label=title,
            kind="select",
            default=default,
            required=True,
            options=[dict(value=k, label=v) for k, v in options.items()],
        )

    if code == "incoming_transfer":
        return [
            field("incoming_kind", "Тип поступления", INCOMING_KINDS, "bank_transfer"),
            field("bank_country", "Банк отправителя", BANK_COUNTRIES, "RU"),
        ]
    if code == "salary":
        return [
            field(
                "income_basis",
                "Основание зарплаты",
                {"payroll_registry": "Зарплатный реестр"},
                "payroll_registry",
            )
        ]
    return []


def source_for(details):
    kind = details.get("incoming_kind")
    if kind not in INCOMING_KINDS:
        raise ValueError("Выберите тип поступления")
    expected = (
        {"incoming_kind", "bank_country"}
        if kind == "bank_transfer"
        else {"incoming_kind"}
    )
    if set(details) != expected:
        raise ValueError("Поля поступления не соответствуют выбранному типу")
    if kind == "bank_transfer":
        if details["bank_country"] not in BANK_COUNTRIES:
            raise ValueError("Выберите страну банка")
        return "domestic_bank" if details["bank_country"] == "RU" else "foreign_bank_kg"
    return "payment_service" if kind == "payment_service" else "crypto_exchange"


def allowed_party(code, party, details):
    if code == "incoming_transfer":
        return (
            (
                party["kind"] == "institution"
                and party.get("category") == "crypto_exchange"
            )
            if details.get("incoming_kind") == "exchange_withdrawal"
            else party["kind"] == "person"
        )
    if code == "salary":
        return party["kind"] == "institution" and party.get("category") == "employer"
    if code == "card_transfer":
        return party["kind"] == "person"
    return code == "purchase" and party["kind"] == "merchant"


class HistoricalOperationV9(HistoricalOperation):
    incoming_kind: (
        Literal["bank_transfer", "payment_service", "exchange_withdrawal", "crypto_p2p"]
        | None
    ) = None
    bank_country: Literal["RU", "KG"] | None = None
    channel: Literal["bank", "branch", "atm", "mobile", "web"] | None = None
    income_basis: Literal["payroll_registry"] | None = None

    @model_validator(mode="after")
    def applicable(self):
        if self.operation_code != "incoming_transfer" and (
            self.incoming_kind or self.bank_country
        ):
            raise ValueError("Тип поступления неприменим к исторической операции")
        if self.bank_country and self.incoming_kind != "bank_transfer":
            raise ValueError("Страна банка применима только к банковскому переводу")
        if self.income_basis and self.operation_code != "salary":
            raise ValueError("Основание зарплаты неприменимо")
        channels = {
            "incoming_transfer": {"bank"},
            "salary": {"bank"},
            "card_transfer": {"mobile", "web", "branch"},
            "cash_withdrawal": {"atm", "branch"},
            "purchase": set(),
        }
        if self.channel and self.channel not in channels[self.operation_code]:
            raise ValueError("Канал неприменим к исторической операции")
        return self


class HistoryV9(History):
    operations: list[HistoricalOperationV9] | None = Field(max_length=10000)


class BehaviorV9(ExpandedBehavior):
    history: HistoryV9

    @model_validator(mode="after")
    def semantic_history(self):
        parties = {p.id: p.model_dump() for p in self.counterparties}
        for party in parties.values():
            if party["kind"] != "person" and party["personal_relationship"] != "unknown":
                raise ValueError("Личное знакомство неприменимо к организации")
            if party["kind"] == "person" and party.get("category") is not None:
                raise ValueError("Физическое лицо не может иметь категорию организации")
            if party.get("category") in {"employer", "crypto_exchange"} and party["kind"] != "institution":
                raise ValueError("Работодатель и биржа должны быть организациями")
        exchanges = [
            p for p in parties.values() if p.get("category") == "crypto_exchange"
        ]
        if len(exchanges) != 1 or exchanges[0]["kind"] != "institution":
            raise ValueError("Каталог v9 требует одну криптобиржу")
        for op in self.history.operations or []:
            if op.operation_code == "cash_withdrawal":
                continue
            party = parties[op.counterparty_id]
            if op.operation_code == "incoming_transfer" and op.incoming_kind is None:
                # Missing observation must not be inferred from a party's name.
                if party["kind"] == "merchant" or party.get("category") == "employer":
                    raise ValueError(
                        "Сторона не подходит для исторического поступления"
                    )
            elif not allowed_party(
                op.operation_code, party, {"incoming_kind": op.incoming_kind}
            ):
                raise ValueError("Историческая сторона не соответствует типу операции")
        return self


def validate_config(config):
    if config.get("schema_version") != 9:
        raise ValueError("Ожидается контракт v9")
    BehaviorV9.model_validate(config["behavior"])


def resource_config(config):
    """Lossless financial projection; new observations remain in original snapshot."""
    validate_config(config)
    result = deepcopy(config)
    result["schema_version"] = 8
    for event in result["behavior"]["history"]["operations"] or []:
        for key in ("incoming_kind", "bank_country", "channel", "income_basis"):
            event.pop(key, None)
    return result


def canonical_steps(steps, config):
    from src.aml_workshop_simulator.services.counterparties import (
        canonical_expanded_steps,
    )

    validate_config(config)
    parties = {p["id"]: p for p in config["behavior"]["counterparties"]}
    original, projected = [], []
    for raw in steps:
        step = (
            raw.model_dump(mode="json") if hasattr(raw, "model_dump") else deepcopy(raw)
        )
        code = step["card"]["code"]
        details = step.get("action_details", {})
        if code == "incoming_transfer":
            source = source_for(details)
        elif code == "salary":
            if details != {"income_basis": "payroll_registry"}:
                raise ValueError(
                    "В v9 зарплата поступает только по зарплатному реестру"
                )
        elif details:
            raise ValueError("Параметры неприменимы к операции")
        role = (
            "sender_id" if code in ("incoming_transfer", "salary") else "recipient_id"
        )
        if code != "cash_withdrawal":
            party = parties.get(step.get(role))
            if party is None or not allowed_party(code, party, details):
                raise ValueError("Сторона не соответствует типу операции")
        original.append(deepcopy(details))
        if code == "incoming_transfer":
            step["action_details"] = {"transfer_source": source}
        projected.append(step)
    canonical = canonical_expanded_steps(projected, resource_config(config))
    for step, details in zip(canonical, original):
        step["action_details"] = details
    return canonical


def resource_steps(steps, config):
    result = canonical_steps(steps, config)
    for step in result:
        if step["card"]["code"] == "incoming_transfer":
            step["action_details"] = {
                "transfer_source": source_for(step["action_details"])
            }
    return result


def evaluate(steps, config):
    from src.aml_workshop_simulator.services.expanded_simulation import (
        evaluate_expanded_scenario,
    )
    canonical = canonical_steps(steps, config)
    result = evaluate_expanded_scenario(
        resource_steps(steps, config), resource_config(config)
    )
    for row, step in zip(result["per_step"], canonical):
        if step["card"]["code"] == "incoming_transfer":
            row["detail_factors"] = [dict(field_key=key, field_label=next(f["label"] for f in fields_for("incoming_transfer") if f["key"] == key), value=value,
                                         value_label=(INCOMING_KINDS if key == "incoming_kind" else BANK_COUNTRIES)[value], risk_points="0", description="Наблюдаемый параметр поступления; не правило риска")
                                     for key, value in step["action_details"].items()]
    return result


def new_config(v8_config):
    """Create a new configuration, never reinterpret a saved v8 round."""
    result = deepcopy(v8_config)
    result["schema_version"] = 9
    result.pop("risk_model", None)
    result.pop("config_version", None)
    for p in result["behavior"]["counterparties"]:
        if p["id"] == "A":
            p["name"] = "Алексей"
        elif p["id"] == "B":
            p["name"] = "Борис"
        elif p["id"] in {"C", "D"}:
            p["name"] = f"Получатель {p['id']} — реквизиты различимы"
    result["behavior"]["counterparties"].append(
        dict(
            id="exchange",
            name="Криптобиржа",
            kind="institution",
            category="crypto_exchange",
            information_status="sufficient",
            personal_relationship="unknown",
        )
    )
    validate_config(result)
    return result
