"""Shared helpers of the administrator API."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.domain.rules import card_spec_from_row
from src.aml_workshop_simulator.schemas.admin import RoundAdminOut
from src.aml_workshop_simulator.schemas.game_config_validation import (
    validate_config_against_catalog,
)


def round_out(round_obj: Round) -> RoundAdminOut:
    return RoundAdminOut(
        id=round_obj.id,
        title=round_obj.title,
        status=round_obj.status,
        config_revision=round_obj.config_revision,
        game_config=round_obj.game_config or {},
        scoring_summary=round_obj.scoring_summary,
        created_at=round_obj.created_at,
        activated_at=round_obj.activated_at,
        closed_at=round_obj.closed_at,
        scoring_started_at=round_obj.scoring_started_at,
        scoring_error=round_obj.scoring_error,
        completed_at=round_obj.completed_at,
    )


def config_version(game_config: dict[str, Any]) -> str:
    payload = {
        key: value for key, value in game_config.items() if key != "config_version"
    }
    blob = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return f"round-config-v{game_config.get('schema_version', 5)}:sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


def validate_game_config(
    db_cards: list[ActionCard], game_config: dict[str, Any]
) -> None:
    """Validate new settings against active cards, preserving the HTTP error contract."""
    available = {
        (card.code, card.version): card_spec_from_row(card)
        for card in db_cards
        if card.is_active
    }
    try:
        validate_config_against_catalog(available, game_config)
    except ValueError as error:
        violations = getattr(error, "violations", None)
        raise Conflict(
            str(error),
            code="round_configuration_invalid",
            details={"violations": violations} if violations else None,
        ) from error
