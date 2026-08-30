"""The channel matrix, enforced at the ruleset level.

Documented contract (docs/chain-validation-matrix.md, CH-*): each card version
declares its own channel list, every declared channel is accepted, and every
other *known* channel — plus any unknown string — is rejected with an
actionable message. `bank` and `branch` are distinct: no alias exists.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aml_workshop_simulator.domain.catalog import CARD_CATALOG, catalog_channels
from aml_workshop_simulator.domain.channels import ALL_CHANNELS
from aml_workshop_simulator.domain.rules import (
    StructuralError,
    evaluate_scenario,
    validate_structure,
)
from tests.unit.conftest import make_step

#: The contract this project is required to implement.
EXPECTED_MATRIX = {
    "salary": ("bank", "branch", "mobile"),
    "cash_deposit": ("atm", "branch"),
    "card_transfer": ("mobile", "web", "branch"),
    "cash_withdrawal": ("atm", "branch"),
}

ALLOWED_PAIRS = [
    (code, channel) for code, channels in EXPECTED_MATRIX.items() for channel in channels
]
DISALLOWED_PAIRS = [
    (code, channel)
    for code, channels in EXPECTED_MATRIX.items()
    for channel in ALL_CHANNELS
    if channel not in channels
]


def test_global_channel_enum_is_exactly_the_five_known_values() -> None:
    assert set(ALL_CHANNELS) == {
        "bank",
        "branch",
        "atm",
        "mobile",
        "web",
    }


def test_catalog_matches_the_documented_matrix() -> None:
    assert {entry["code"] for entry in CARD_CATALOG} == set(EXPECTED_MATRIX)
    for code, channels in EXPECTED_MATRIX.items():
        assert catalog_channels(code, 1) == channels


@pytest.mark.parametrize(("code", "channel"), ALLOWED_PAIRS, ids=[
    f"{code}-{channel}" for code, channel in ALLOWED_PAIRS
])
def test_declared_channel_is_accepted(spec_by_code, specs, game_config, code, channel) -> None:
    spec = spec_by_code[code]
    steps = [make_step(spec, spec.min_amount, channel=channel)]

    snapshot = evaluate_scenario(steps, specs, game_config)
    channel_problems = [
        violation
        for violation in snapshot["violations"]
        if violation["reason"] == "channel_not_allowed"
    ]
    assert channel_problems == []
    stored = snapshot["per_step"][-1]
    assert stored["card_code"] == code


@pytest.mark.parametrize(("code", "channel"), DISALLOWED_PAIRS, ids=[
    f"{code}-{channel}" for code, channel in DISALLOWED_PAIRS
])
def test_other_known_channel_is_rejected(spec_by_code, specs, game_config, code, channel) -> None:
    spec = spec_by_code[code]
    steps = [make_step(spec, spec.min_amount, channel=channel)]

    with pytest.raises(StructuralError) as raised:
        evaluate_scenario(steps, specs, game_config)

    violation = next(
        item for item in raised.value.violations if item.reason == "channel_not_allowed"
    )
    assert violation.field == "context.channel"
    assert violation.current == channel
    assert violation.step_id == steps[0]["step_id"]
    assert violation.allowed == ", ".join(EXPECTED_MATRIX[code])


def test_bank_and_branch_are_not_aliases(spec_by_code, specs, game_config) -> None:
    """cash_deposit allows branch but not bank; salary allows both explicitly."""
    deposit = spec_by_code["cash_deposit"]
    with pytest.raises(StructuralError):
        evaluate_scenario(
            [make_step(deposit, deposit.min_amount, channel="bank")], specs, game_config
        )
    snapshot = evaluate_scenario(
        [make_step(deposit, deposit.min_amount, channel="branch")], specs, game_config
    )
    assert not [
        item for item in snapshot["violations"] if item["reason"] == "channel_not_allowed"
    ]


def test_rejection_message_names_step_field_value_and_options(
    spec_by_code, specs, game_config
) -> None:
    spec = spec_by_code["card_transfer"]
    step = make_step(spec, Decimal("10000.00"), channel="atm")
    violations = validate_structure([step], specs)
    message = violations[0].message
    assert "Перевести по карте" in message
    assert "Канал" in message
    assert "Банкомат" in message  # the rejected value, localised
    assert "Мобильное приложение" in message and "Отделение банка" in message
    assert "Выберите" in message  # how to fix it
