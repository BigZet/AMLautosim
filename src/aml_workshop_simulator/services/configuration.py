"""Freeze the complete contract a round uses, including catalog details."""

import json
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from aml_workshop_simulator.core.game_config import load_config
from aml_workshop_simulator.domain.rules import CardSpec, card_spec_from_row


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


def _drop_references(config: dict[str, Any], missing: set[tuple[str, int]]) -> None:
    """Remove every reference to card versions this build no longer ships."""
    for key in ("operations", "card_versions"):
        refs = config.get(key)
        if not refs:
            continue
        config[key] = [
            ref for ref in refs if (ref["code"], ref["version"]) not in missing
        ]


def freeze_game_config(
    config: dict[str, Any],
    cards: list[Any],
    previous: dict[str, Any] | None = None,
    *,
    strict: bool = True,
    dropped: list[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Copy missing settings from files/DB once; never overwrite a frozen value.

    `strict` decides what happens when a round names a card version this build
    no longer ships. An administrator who submits such a configuration made a
    mistake and has to be told, so every API path keeps the default and answers
    409. The upgrade path of an existing installation has nobody to tell: it
    either drops the dead reference or the API never starts again, so
    `scripts.seed_database` passes ``strict=False`` and reports through
    `dropped` what it removed.

    Dropping matches what the round already does at play time -- `RoundPolicy`
    skips an operation whose card version is gone -- so this only makes the
    frozen snapshot agree with the runtime.
    """
    result = deepcopy(config)
    result.setdefault("resource_rules", load_config("resource_rules.json"))
    result["scoring"].setdefault("rules", load_config("risk_rules.json"))
    if not result.get("card_snapshots"):
        refs = result.get("operations") or result.get("card_versions") or []
        pairs = {(ref["code"], ref["version"]) for ref in refs}
        known = {(card.code, card.version): card_spec_from_row(card) for card in cards}
        known.update(snapshot_specs(previous or {}))
        specs = [known[pair] for pair in sorted(pairs) if pair in known]
        missing = pairs - {spec.key for spec in specs}
        if missing:
            if strict:
                raise ValueError("Cannot freeze round: a referenced card is missing")
            if not specs:
                # Nothing survives. An empty `operations` block would read as a
                # legacy snapshot and expose the whole current catalog, so the
                # round is left exactly as it was: the API still starts and an
                # operator decides what to do with it.
                return result
            _drop_references(result, missing)
            if dropped is not None:
                dropped.extend(sorted(missing))
        result["card_snapshots"] = json.loads(
            json.dumps([asdict(spec) for spec in specs], default=str)
        )
    return result
