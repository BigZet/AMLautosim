"""Canonical, versioned catalog of action cards.

This module is the single place where a card version is described. Everything
else derives from it:

* `scripts/seed_database.py` writes each entry into `action_cards`, storing the
  UI/validation contract in `action_cards.parameter_schema` (JSONB);
* `GET /api/v1/rounds/{round_id}/cards` serves that stored contract verbatim,
  so the participant UI can only offer what the card version declares;
* `domain.rules` validates every step against the same stored contract.

There is therefore exactly one channel list per card version, shared by the UI
and the server. No implicit aliases exist between channel values.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.domain.action_parameters import (
    action_fields_for,
    context_fields_for,
)
from src.aml_workshop_simulator.domain.channels import Channel

CARD_SCHEMA_VERSION = 1

#: Quota buckets a card contributes to. Context-driven buckets
#: (`anonymous`, `high_risk_country`) are added by the ruleset, not by the card.
QUOTA_CATEGORIES = ("cash", "international", "crypto", "anonymous", "high_risk_country")


CARD_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "code": "salary",
        "version": 1,
        "title": "Получить зарплату",
        "description": "Регулярное поступление от известного работодателя.",
        "category": "Поступление",
        "flow": "credit",
        "risk_weight": Decimal("0.00"),
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 0,
        "fee_rate": Decimal("0.000000"),
        "min_amount": Decimal("10000.00"),
        "max_amount": Decimal("150000.00"),
        "max_frequency": 2,
        "round_frequency_limit": 2,
        "requires_card_code": None,
        "quota_category": None,
        "channels": (Channel.bank, Channel.branch, Channel.mobile),
    },
    {
        "code": "cash_deposit",
        "version": 1,
        "title": "Внести наличные",
        "description": "Пополнение счета через банкомат или кассу.",
        "category": "Наличные",
        "flow": "credit",
        "risk_weight": Decimal("12.00"),
        "energy_cost": 2,
        "time_cost": 2,
        "trust_cost": 5,
        "fee_rate": Decimal("0.000000"),
        "min_amount": Decimal("5000.00"),
        "max_amount": Decimal("150000.00"),
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": None,
        "quota_category": "cash",
        "channels": (Channel.atm, Channel.branch),
    },
    {
        "code": "card_transfer",
        "version": 1,
        "title": "Перевести по карте",
        "description": "Перевод другому клиенту банка.",
        "category": "Перевод",
        "flow": "debit",
        "risk_weight": Decimal("5.00"),
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 1,
        "fee_rate": Decimal("0.005000"),
        "min_amount": Decimal("1000.00"),
        "max_amount": Decimal("500000.00"),
        "max_frequency": 5,
        "round_frequency_limit": 7,
        "requires_card_code": None,
        "quota_category": None,
        "channels": (Channel.mobile, Channel.web, Channel.branch),
    },
    {
        "code": "international",
        "version": 1,
        "title": "Международный перевод",
        "description": "Отправка средств в другую страну.",
        "category": "Перевод",
        "flow": "debit",
        "risk_weight": Decimal("18.00"),
        "energy_cost": 3,
        "time_cost": 3,
        "trust_cost": 12,
        "fee_rate": Decimal("0.020000"),
        "min_amount": Decimal("5000.00"),
        "max_amount": Decimal("180000.00"),
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": None,
        "quota_category": "international",
        "channels": (Channel.web, Channel.branch),
    },
    {
        "code": "cash_withdrawal",
        "version": 1,
        "title": "Снять наличные",
        "description": "Получение наличных вскоре после поступления.",
        "category": "Наличные",
        "flow": "debit",
        "risk_weight": Decimal("14.00"),
        "energy_cost": 2,
        "time_cost": 2,
        "trust_cost": 8,
        "fee_rate": Decimal("0.010000"),
        "min_amount": Decimal("5000.00"),
        "max_amount": Decimal("120000.00"),
        "max_frequency": 4,
        "round_frequency_limit": 4,
        "requires_card_code": None,
        "quota_category": "cash",
        "channels": (Channel.atm, Channel.branch),
    },
    {
        "code": "crypto_exchange",
        "version": 1,
        "title": "Купить криптовалюту",
        "description": "Перевод средств на криптовалютную площадку.",
        "category": "Цифровые активы",
        "flow": "debit",
        "risk_weight": Decimal("20.00"),
        "energy_cost": 3,
        "time_cost": 3,
        "trust_cost": 15,
        "fee_rate": Decimal("0.015000"),
        "min_amount": Decimal("5000.00"),
        "max_amount": Decimal("100000.00"),
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": None,
        "quota_category": "crypto",
        "channels": (Channel.exchange, Channel.web),
    },
    {
        "code": "online_purchase",
        "version": 1,
        "title": "Оплатить покупку",
        "description": "Оплата товара в интернет-магазине.",
        "category": "Покупка",
        "flow": "debit",
        "risk_weight": Decimal("2.00"),
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 0,
        "fee_rate": Decimal("0.000000"),
        "min_amount": Decimal("1000.00"),
        "max_amount": Decimal("250000.00"),
        "max_frequency": 5,
        "round_frequency_limit": 6,
        "requires_card_code": None,
        "quota_category": None,
        "channels": (Channel.mobile, Channel.web),
    },
    {
        "code": "refund",
        "version": 1,
        "title": "Получить возврат",
        "description": "Возврат возможен только после покупки в этой цепочке.",
        "category": "Поступление",
        "flow": "credit",
        "risk_weight": Decimal("4.00"),
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 2,
        "fee_rate": Decimal("0.000000"),
        "min_amount": Decimal("1000.00"),
        "max_amount": Decimal("150000.00"),
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "requires_card_code": "online_purchase",
        "quota_category": None,
        "channels": (Channel.mobile, Channel.web),
    },
)


def build_parameter_schema(entry: dict[str, Any]) -> dict[str, Any]:
    """Contract stored in `action_cards.parameter_schema` for one card version.

    The dict is JSON-serialisable and contains everything both the UI and the
    server need in order to agree on what a step of this card may contain.
    """
    code = entry["code"]
    return {
        "schema_version": CARD_SCHEMA_VERSION,
        "channels": [str(channel) for channel in entry["channels"]],
        "round_frequency_limit": entry["round_frequency_limit"],
        "quota_category": entry["quota_category"],
        "description": entry["description"],
        "context_fields": [dict(field) for field in context_fields_for(code)],
        "fields": [dict(field) for field in action_fields_for(code)],
    }


def catalog_entry(code: str, version: int = 1) -> dict[str, Any]:
    for entry in CARD_CATALOG:
        if entry["code"] == code and entry["version"] == version:
            return entry
    raise KeyError(f"unknown card version {code} v{version}")


def catalog_channels(code: str, version: int = 1) -> tuple[str, ...]:
    """Allowed channels of one card version, as plain strings."""
    return tuple(str(channel) for channel in catalog_entry(code, version)["channels"])


CARD_CODES: tuple[str, ...] = tuple(entry["code"] for entry in CARD_CATALOG)
