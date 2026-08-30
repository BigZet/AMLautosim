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
from src.aml_workshop_simulator.domain.round_policy import (
    action_param,
    context_param,
)

CARD_SCHEMA_VERSION = 2

#: Quota buckets a card contributes to. The context-driven `anonymous` bucket
#: is added by the ruleset, not by the card.
QUOTA_CATEGORIES = ("cash", "anonymous")

#: Operations a freshly created round offers by default.
#:
#: This is also the complete catalog. Keeping one canonical list prevents
#: removed operations from resurfacing in seeds, round presets or the UI.
DEFAULT_OPERATION_CODES: tuple[str, ...] = (
    "salary",
    "cash_deposit",
    "card_transfer",
    "cash_withdrawal",
)

#: On top of amount and frequency a participant edits at most two parameters
#: per operation. The channel is always one of them, so the channel matrix
#: stays playable; the second one is the risk lever that makes the operation
#: interesting and keeps every round-level limit reachable:
#:
#: * `time_of_day`     -> night operation quota
#: * `recipient_type`  -> anonymous recipient quota
#: * card-specific action detail -> the operation's own risk story
DEFAULT_VISIBLE_PARAMS: dict[str, tuple[str, ...]] = {
    "salary": (context_param("time_of_day"),),
    "cash_deposit": (action_param("funds_source"),),
    "card_transfer": (context_param("recipient_type"),),
    "cash_withdrawal": (context_param("time_of_day"),),
}

#: Repeat counts are only offered where splitting an amount into several
#: transactions is a real move (structuring). Everywhere else the frequency is
#: pinned to 1 by the server.
DEFAULT_SHOW_FREQUENCY: dict[str, bool] = {
    "salary": False,
    "cash_deposit": True,
    "card_transfer": True,
    "cash_withdrawal": True,
}


def default_visible_params(code: str) -> tuple[str, ...]:
    """Channel plus the card's own risk lever, in display order."""
    return ("channel",) + DEFAULT_VISIBLE_PARAMS.get(code, ())


def default_show_frequency(code: str) -> bool:
    return DEFAULT_SHOW_FREQUENCY.get(code, True)


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
        "code": "cash_withdrawal",
        "version": 1,
        "title": "Снять наличные",
        "description": "Получение наличных вскоре после поступления.",
        "category": "Наличные",
        "flow": "debit",
        "risk_weight": Decimal("14.00"),
        "energy_cost": 2,
        "time_cost": 2,
        "fee_rate": Decimal("0.010000"),
        "min_amount": Decimal("5000.00"),
        "max_amount": Decimal("120000.00"),
        "max_frequency": 4,
        "round_frequency_limit": 4,
        "requires_card_code": None,
        "quota_category": "cash",
        "channels": (Channel.atm, Channel.branch),
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
        "default_visible_params": list(default_visible_params(code)),
        "default_show_frequency": default_show_frequency(code),
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
