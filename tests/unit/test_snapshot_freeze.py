"""Freezing a round snapshot against the card catalog.

`freeze_game_config` writes the card details a round plays by, once, and never
rewrites them. The interesting case is an installation upgraded across a
catalog reduction: its rounds name card versions that no longer exist.
"""

from __future__ import annotations

import pytest

from src.aml_workshop_simulator.domain.rules import REFERENCE_GAME_CONFIG
from src.aml_workshop_simulator.services.configuration import freeze_game_config

REMOVED_CARD = {
    "code": "international",
    "version": 1,
    "visible_params": [],
    "show_frequency": False,
}


class _Row:
    """The `action_cards` row as `card_spec_from_row` reads it."""

    def __init__(self, spec) -> None:
        self.id = spec.id
        self.code = spec.code
        self.version = spec.version
        self.title = spec.title
        self.category = spec.category
        self.flow = spec.flow
        self.risk_weight = spec.risk_weight
        self.energy_cost = spec.energy_cost
        self.time_cost = spec.time_cost
        self.fee_rate = spec.fee_rate
        self.min_amount = spec.min_amount
        self.max_amount = spec.max_amount
        self.max_frequency = spec.max_frequency
        self.requires_card_code = spec.requires_card_code
        self.parameter_schema = {
            "channels": list(spec.channels),
            "round_frequency_limit": spec.round_frequency_limit,
            "quota_category": spec.quota_category,
            "description": spec.description,
            "context_fields": [dict(item) for item in spec.context_fields],
            "fields": [dict(item) for item in spec.fields],
            "default_visible_params": list(spec.default_visible_params),
            "default_show_frequency": spec.default_show_frequency,
        }
        self.is_active = True


@pytest.fixture()
def rows(specs):
    return [_Row(spec) for spec in specs.values()]


@pytest.fixture()
def unfrozen_config():
    """A round snapshot from before card details were frozen into it."""
    return {
        key: value
        for key, value in REFERENCE_GAME_CONFIG.items()
        if key != "card_snapshots"
    }


def test_a_removed_card_is_rejected_when_an_administrator_submits_it(
    rows, unfrozen_config
):
    """A hand-written configuration naming a missing card is a real error.

    Every API path keeps the strict default so the administrator is told (409)
    instead of quietly getting a round with fewer operations than requested.
    """
    unfrozen_config["operations"] = [*unfrozen_config["operations"], REMOVED_CARD]

    with pytest.raises(ValueError, match="a referenced card is missing"):
        freeze_game_config(unfrozen_config, rows)


def test_a_removed_card_is_dropped_on_the_upgrade_path(rows, unfrozen_config):
    """The seed cannot refuse: refusing means the API never starts again.

    `RoundPolicy` already skips an operation whose card version is gone, so
    dropping the reference makes the frozen snapshot agree with play time.
    """
    unfrozen_config["operations"] = [*unfrozen_config["operations"], REMOVED_CARD]
    unfrozen_config["card_versions"] = [
        {"id": 99, "code": "international", "version": 1}
    ]
    expected = len(unfrozen_config["operations"]) - 1
    dropped: list[tuple[str, int]] = []

    frozen = freeze_game_config(
        unfrozen_config, rows, strict=False, dropped=dropped
    )

    assert dropped == [("international", 1)]
    assert len(frozen["operations"]) == expected
    assert "international" not in {op["code"] for op in frozen["operations"]}
    # The dead reference goes from both places that can carry it.
    assert frozen["card_versions"] == []
    assert len(frozen["card_snapshots"]) == expected


def test_a_round_whose_every_card_disappeared_is_left_untouched(unfrozen_config):
    """Dropping everything would make the round read as legacy.

    An empty `operations` block means "no restrictions" to
    `RoundPolicy.from_config`, which would expose the whole current catalog.
    Leaving the round alone keeps the API starting and the round unplayable
    until an operator decides what to do with it.
    """
    dropped: list[tuple[str, int]] = []

    frozen = freeze_game_config(unfrozen_config, [], strict=False, dropped=dropped)

    assert dropped == []
    assert "card_snapshots" not in frozen
    assert frozen["operations"] == unfrozen_config["operations"]


def test_an_already_frozen_round_is_never_reexamined(rows):
    """A frozen snapshot is the contract; the catalog no longer speaks for it."""
    frozen = freeze_game_config(dict(REFERENCE_GAME_CONFIG), rows)
    assert frozen["card_snapshots"], "the freeze must write the card details"

    frozen["operations"] = [*frozen["operations"], REMOVED_CARD]

    again = freeze_game_config(frozen, rows)
    assert again["card_snapshots"] == frozen["card_snapshots"]
    # Strict mode does not even look: the round already carries its own cards.
    assert len(again["operations"]) == len(frozen["operations"])
