"""Canonical, versioned catalog of action cards.

This module loads card definitions from config/operations.json and parameter
contracts from config/parameters.json. Everything else derives from those files:

* `scripts/seed_database.py` writes each entry into `action_cards`, storing the
  UI/validation contract in `action_cards.parameter_schema` (JSONB);
* `GET /api/v1/rounds/{round_id}/cards` serves the round's frozen contract,
  so the participant UI can only offer what the card version declares;
* `domain.rules` validates every step against the same stored contract.

There is therefore exactly one channel list per card version, shared by the UI
and the server. No implicit aliases exist between channel values.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.core.game_config import load_config
from src.aml_workshop_simulator.domain.action_parameters import (
    action_fields_for,
    context_fields_for,
)

_CATALOG = load_config("operations.json")
CARD_SCHEMA_VERSION = _CATALOG["schema_version"]
QUOTA_CATEGORIES = tuple(
    load_config("base_round.json")["constraints"]["category_limits"]
)
DEFAULT_OPERATION_CODES = tuple(
    item["code"] for item in load_config("base_round.json")["operations"]
)

CARD_CATALOG: tuple[dict[str, Any], ...] = tuple(
    {
        **entry,
        **{
            key: Decimal(entry[key])
            for key in ("risk_weight", "fee_rate", "min_amount", "max_amount")
        },
        "channels": tuple(entry["channels"]),
    }
    for entry in _CATALOG["cards"]
)


def default_visible_params(code: str) -> tuple[str, ...]:
    return tuple(catalog_entry(code)["default_visible_params"])


def default_show_frequency(code: str) -> bool:
    return catalog_entry(code)["default_show_frequency"]


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
        "context_fields": deepcopy(list(context_fields_for(code))),
        "fields": deepcopy(list(action_fields_for(code))),
        "default_visible_params": list(entry["default_visible_params"]),
        "default_show_frequency": entry["default_show_frequency"],
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
