from __future__ import annotations

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
