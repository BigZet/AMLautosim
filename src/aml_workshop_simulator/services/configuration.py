"""Freeze the complete contract a round uses, including catalog details."""

import json
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.domain.rules import CardSpec, card_spec_from_row


def snapshot_specs(config: dict[str, Any]) -> dict[tuple[str, int], CardSpec]:
    result = {}
    for item in config.get("card_snapshots", []):
        data = deepcopy(item)
        for key in ("risk_weight", "fee_rate", "min_amount", "max_amount"):
            data[key] = Decimal(data[key])
        for key in ("channels", "context_fields", "fields", "default_visible_params"):
            data[key] = tuple(data[key])
        spec = CardSpec(**data)
        result[spec.key] = spec
    return result


def freeze_game_config(
    config: dict[str, Any], cards: list[ActionCard]
) -> dict[str, Any]:
    """Create a server-owned snapshot from validated settings and current cards."""
    result = deepcopy(config)
    pairs = {(ref["code"], ref["version"]) for ref in config["operations"]}
    known = {(card.code, card.version): card_spec_from_row(card) for card in cards}
    if not pairs <= known.keys():
        raise ValueError("Cannot freeze round: a referenced card is missing")
    result["card_snapshots"] = json.loads(
        json.dumps([asdict(known[pair]) for pair in sorted(pairs)], default=str)
    )
    return result
