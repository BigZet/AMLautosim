from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from src.aml_workshop_simulator.core.game_config import load_config

_PARAMETERS = load_config("parameters.json")
CONTEXT_FIELDS: dict[str, dict[str, Any]] = _PARAMETERS["context_fields"]
ACTION_CONTEXT_FIELDS = _PARAMETERS["action_context_fields"]
ACTION_PARAMETER_SCHEMAS = {
    code: tuple(fields) for code, fields in _PARAMETERS["action_fields"].items()
}


def context_fields_for(card_code: str) -> tuple[dict[str, Any], ...]:
    """Declarative context-field specs that apply to one card code."""
    return tuple(
        deepcopy(CONTEXT_FIELDS[key])
        for key in ACTION_CONTEXT_FIELDS.get(card_code, ())
    )


def action_fields_for(card_code: str) -> tuple[dict[str, Any], ...]:
    """Declarative action-detail field specs for one card code."""
    return deepcopy(ACTION_PARAMETER_SCHEMAS.get(card_code, ()))


def context_value_label(field_key: str, value: Any) -> str:
    field = CONTEXT_FIELDS.get(field_key)
    if field is None:
        return str(value)
    if field["kind"] == "toggle":
        return "Да" if value else "Нет"
    option = next(
        (item for item in field.get("options", []) if item["value"] == value),
        None,
    )
    return option["label"] if option else str(value)


def option_label(fields: Sequence[dict[str, Any]], field_key: str, value: Any) -> str:
    """Label of one option inside a declarative field list."""
    for field in fields:
        if field["key"] != field_key:
            continue
        option = next(
            (item for item in field.get("options", []) if item["value"] == value),
            None,
        )
        return option["label"] if option else str(value)
    return str(value)
