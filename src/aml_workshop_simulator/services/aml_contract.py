"""Runtime financial identity shared with the independently audited data contract."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
from src.aml_workshop_simulator.domain.catalog import SEED_CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
from src.aml_workshop_simulator.domain.round_policy import CARD_OVERRIDE_KEYS


def check(condition, message):
    if not condition:
        raise ValueError(message)


def financial_projection(config):
    """Effective resources/constraints/cards; observation text and IDs are irrelevant."""
    ignored = {
        "id",
        "title",
        "description",
        "label",
        "help",
        "category",
        "default_visible_params",
        "risk_weight",
        "risk_points",
    }

    def normalize(value):
        if isinstance(value, dict):
            if "value" in value:
                value = {"energy_cost": 0, "time_cost": 0, **value}
            if "key" in value and "kind" in value:
                value = {"required": True, **value}
            return {k: normalize(v) for k, v in value.items() if k not in ignored}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if type(value) in (int, float, Decimal) or isinstance(value, str):
            try:
                return str(Decimal(str(value)).normalize())
            except InvalidOperation:
                return value
        return value

    cards = {(c["code"], c["version"]): c for c in config["card_snapshots"]}
    check(
        len(cards) == len(config["card_snapshots"]),
        "Duplicate cards in financial contract",
    )
    operations = {}
    for operation in config["operations"]:
        key = (operation["code"], operation["version"])
        check(key in cards, "Missing card in financial contract")
        effective = {
            **cards[key],
            **{
                k: operation[k]
                for k in CARD_OVERRIDE_KEYS
                if operation.get(k) is not None
            },
        }
        operations[f"{key[0]}:{key[1]}"] = normalize(effective)
    return {
        **{
            key: normalize(config[key])
            for key in (
                "resources",
                "objectives",
                "constraints",
                "resource_rules",
                "ruleset_version",
            )
        },
        "cards": operations,
        "turnover": normalize(config["behavior"]["turnover"]),
        "purchases": normalize(config["behavior"].get("purchases")),
        "snapshot_card_keys": sorted(f"{k[0]}:{k[1]}" for k in cards),
    }


@lru_cache(maxsize=1)
def fixed_financial_contract():
    reference = expanded_game_config(
        datetime.fromisoformat("2026-09-13T09:00:00+03:00")
    )
    reference["card_snapshots"] = [
        asdict(card_spec_from_catalog(card, i))
        for i, card in enumerate(SEED_CARD_CATALOG, 1)
    ]
    return financial_projection(reference)
