"""Freeze the complete contract a round uses, including catalog details."""

import json
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.core.game_config import load_config
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
    config: dict[str, Any], cards: list[Any], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Copy missing settings from files/DB once; never overwrite a frozen value."""
    result = deepcopy(config)
    result.setdefault("resource_rules", load_config("resource_rules.json"))
    result["scoring"].setdefault("rules", load_config("risk_rules.json"))
    if not result.get("card_snapshots"):
        refs = result.get("operations") or result.get("card_versions") or []
        pairs = {(ref["code"], ref["version"]) for ref in refs}
        known = {(card.code, card.version): card_spec_from_row(card) for card in cards}
        known.update(snapshot_specs(previous or {}))
        specs = [known[pair] for pair in sorted(pairs) if pair in known]
        if {spec.key for spec in specs} != pairs:
            raise ValueError("Cannot freeze round: a referenced card is missing")
        result["card_snapshots"] = json.loads(
            json.dumps([asdict(spec) for spec in specs], default=str)
        )
    return result
