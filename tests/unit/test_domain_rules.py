"""Golden ruleset tests for `game-rules-v3`.

Covers the equivalence classes and boundaries from
docs/chain-validation-matrix.md: amounts, frequencies, quotas, sequence rules,
resource exhaustion and the structural/business split.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest

from src.aml_workshop_simulator.domain.rules import (
    REFERENCE_GAME_CONFIG,
    StructuralError,
    evaluate_scenario,
    money,
    specs_by_key,
    submit_blockers,
    validate_structure,
)
from tests.unit.conftest import make_step

CENT = Decimal("0.01")


def reasons(snapshot: dict) -> list[str]:
    return [violation["reason"] for violation in snapshot["violations"]]


def structural_reasons(error: StructuralError) -> list[str]:
    return [violation.reason for violation in error.violations]


# --------------------------------------------------------------------------
# Money and flow
# --------------------------------------------------------------------------


def test_credit_and_debit_flows_use_decimal_with_banker_rounding(
    spec_by_code, specs, game_config
) -> None:
    salary = spec_by_code["salary"]
    transfer = spec_by_code["card_transfer"]
    # 12 345.67 * 0.005 = 61.72835 -> 61.73 with ROUND_HALF_EVEN
    steps = [
        make_step(salary, Decimal("100000.00")),
        make_step(transfer, Decimal("12345.67")),
    ]
    snapshot = evaluate_scenario(steps, specs, game_config)
    assert snapshot["totals"]["fees"] == "61.73"
    assert snapshot["totals"]["gross_inflow"] == "100000.00"
    assert snapshot["totals"]["gross_outflow"] == "12345.67"
    expected = money(Decimal("250000.00") + Decimal("100000.00") - Decimal("12345.67") - Decimal("61.73"))
    assert snapshot["resources_after"]["balance"] == str(expected)


def test_fee_is_charged_on_gross_amount_times_frequency(spec_by_code, specs, game_config) -> None:
    salary = spec_by_code["salary"]
    transfer = spec_by_code["card_transfer"]
    steps = [
        make_step(salary, Decimal("100000.00")),
        make_step(transfer, Decimal("10000.00"), frequency=3),
    ]
    snapshot = evaluate_scenario(steps, specs, game_config)
    assert snapshot["totals"]["gross_outflow"] == "30000.00"
    assert snapshot["totals"]["fees"] == "150.00"  # 30000 * 0.005


# --------------------------------------------------------------------------
# Amount boundaries
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code", ["salary", "cash_deposit", "card_transfer", "cash_withdrawal"]
)
def test_amount_boundaries(spec_by_code, specs, game_config, code) -> None:
    spec = spec_by_code[code]
    below = evaluate_scenario(
        [make_step(spec, spec.min_amount - CENT)], specs, game_config
    )
    assert "amount_out_of_range" in reasons(below)

    at_min = evaluate_scenario([make_step(spec, spec.min_amount)], specs, game_config)
    assert "amount_out_of_range" not in reasons(at_min)

    at_max = evaluate_scenario([make_step(spec, spec.max_amount)], specs, game_config)
    assert "amount_out_of_range" not in reasons(at_max)

    above = evaluate_scenario(
        [make_step(spec, spec.max_amount + CENT)], specs, game_config
    )
    assert "amount_out_of_range" in reasons(above)


def test_amount_violation_names_step_field_and_limits(spec_by_code, specs, game_config) -> None:
    spec = spec_by_code["cash_deposit"]
    step = make_step(spec, spec.max_amount + CENT)
    snapshot = evaluate_scenario([step], specs, game_config)
    violation = next(
        item for item in snapshot["violations"] if item["reason"] == "amount_out_of_range"
    )
    assert violation["step_id"] == step["step_id"]
    assert violation["field"] == "amount"
    assert violation["current"] == str(spec.max_amount + CENT)
    assert "Сумма" in violation["message"]
    assert "Измените сумму" in violation["message"]


# --------------------------------------------------------------------------
# Frequency boundaries
# --------------------------------------------------------------------------


def test_frequency_boundaries(spec_by_code, specs, game_config) -> None:
    spec = spec_by_code["card_transfer"]
    at_limit = evaluate_scenario(
        [make_step(spec, Decimal("1000.00"), frequency=spec.max_frequency)],
        specs,
        game_config,
    )
    assert "frequency_out_of_range" not in reasons(at_limit)

    above = evaluate_scenario(
        [make_step(spec, Decimal("1000.00"), frequency=spec.max_frequency + 1)],
        specs,
        game_config,
    )
    assert "frequency_out_of_range" in reasons(above)


def test_round_frequency_limit_boundaries(spec_by_code, specs, game_config) -> None:
    """card_transfer: 5 per step, 7 per round."""
    spec = spec_by_code["card_transfer"]
    salary = spec_by_code["salary"]
    other = spec_by_code["cash_withdrawal"]

    def chain(total: int) -> list[dict]:
        first = min(total, spec.max_frequency)
        rest = total - first
        steps = [
            make_step(salary, Decimal("100000.00")),
            make_step(spec, Decimal("1000.00"), frequency=first),
        ]
        if rest:
            steps.append(make_step(other, Decimal("5000.00")))
            steps.append(make_step(spec, Decimal("1000.00"), frequency=rest))
        return steps

    assert "round_frequency_limit_exceeded" not in reasons(
        evaluate_scenario(chain(6), specs, game_config)
    )
    assert "round_frequency_limit_exceeded" not in reasons(
        evaluate_scenario(chain(7), specs, game_config)
    )
    assert "round_frequency_limit_exceeded" in reasons(
        evaluate_scenario(chain(8), specs, game_config)
    )


# --------------------------------------------------------------------------
# Structural failures
# --------------------------------------------------------------------------


def test_unknown_card_version_is_structural(spec_by_code, specs, game_config) -> None:
    spec = spec_by_code["salary"]
    step = make_step(spec, spec.min_amount, card_version=99)
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, game_config)
    assert "unknown_card_version" in structural_reasons(raised.value)


def test_card_id_mismatch_is_structural(spec_by_code, specs, game_config) -> None:
    spec = spec_by_code["salary"]
    step = make_step(spec, spec.min_amount, card_id=spec.id + 100)
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, game_config)
    assert "card_reference_mismatch" in structural_reasons(raised.value)


def test_duplicate_step_id_is_structural(spec_by_code, specs, game_config) -> None:
    spec = spec_by_code["salary"]
    shared = str(uuid.uuid4())
    steps = [
        make_step(spec, spec.min_amount, step_id=shared),
        make_step(spec, spec.min_amount, step_id=shared),
    ]
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario(steps, specs, game_config)
    assert "duplicate_step_id" in structural_reasons(raised.value)


def test_unknown_and_missing_action_parameters_are_structural(
    spec_by_code, specs, game_config
) -> None:
    spec = spec_by_code["cash_deposit"]
    unknown = make_step(spec, spec.min_amount, action_details={"nonexistent": "x"})
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([unknown], specs, game_config)
    assert "unknown_action_parameter" in structural_reasons(raised.value)

    missing = make_step(spec, spec.min_amount)
    missing["action_details"].pop("funds_source")
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([missing], specs, game_config)
    assert "missing_action_parameter" in structural_reasons(raised.value)


def test_invalid_action_option_is_structural(spec_by_code, specs, game_config) -> None:
    spec = spec_by_code["cash_deposit"]
    step = make_step(spec, spec.min_amount, action_details={"funds_source": "nope"})
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, game_config)
    violation = next(
        item for item in raised.value.violations if item.reason == "invalid_action_parameter"
    )
    assert violation.field == "action_details.funds_source"
    assert violation.current == "nope"


def test_context_field_the_card_does_not_declare_must_stay_default(
    spec_by_code, specs, game_config
) -> None:
    """cash_withdrawal declares only time_of_day and velocity."""
    spec = spec_by_code["cash_withdrawal"]
    step = make_step(spec, spec.min_amount, context={"recipient_type": "new_counterparty"})
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, game_config)
    assert "context_field_not_applicable" in structural_reasons(raised.value)


@pytest.mark.parametrize(
    "code", ["salary", "cash_deposit", "card_transfer", "cash_withdrawal"]
)
def test_every_declared_option_of_every_field_is_accepted(
    spec_by_code, specs, game_config, code
) -> None:
    spec = spec_by_code[code]
    for field in spec.fields:
        for option in field["options"]:
            step = make_step(
                spec, spec.min_amount, action_details={field["key"]: option["value"]}
            )
            structural = validate_structure([step], specs)
            assert structural == [], (code, field["key"], option["value"], structural)
    for field in spec.context_fields:
        options = field.get("options") or [{"value": True}, {"value": False}]
        for option in options:
            step = make_step(spec, spec.min_amount, context={field["key"]: option["value"]})
            structural = validate_structure([step], specs)
            assert structural == [], (code, field["key"], option["value"], structural)


# --------------------------------------------------------------------------
# Sequence rules
# --------------------------------------------------------------------------




def test_identical_streak_boundaries(spec_by_code, specs, game_config) -> None:
    salary = spec_by_code["salary"]
    withdrawal = spec_by_code["cash_withdrawal"]
    at_limit = [make_step(withdrawal, Decimal("5000.00")) for _ in range(2)]
    assert "identical_streak_exceeded" not in reasons(
        evaluate_scenario(at_limit, specs, game_config)
    )
    above = [make_step(withdrawal, Decimal("5000.00")) for _ in range(3)]
    assert "identical_streak_exceeded" in reasons(
        evaluate_scenario(above, specs, game_config)
    )
    separated = [
        make_step(withdrawal, Decimal("5000.00")),
        make_step(withdrawal, Decimal("5000.00")),
        make_step(salary, Decimal("10000.00")),
        make_step(withdrawal, Decimal("5000.00")),
    ]
    assert "identical_streak_exceeded" not in reasons(
        evaluate_scenario(separated, specs, game_config)
    )




# --------------------------------------------------------------------------
# Round constraints
# --------------------------------------------------------------------------


def test_max_actions_boundaries(spec_by_code, specs, game_config) -> None:
    transfer = spec_by_code["card_transfer"]
    salary = spec_by_code["salary"]
    codes = [transfer, salary] * 4
    exact = [make_step(codes[index], Decimal("1000.00") if index % 2 == 0 else Decimal("10000.00"))
             for index in range(8)]
    assert "max_actions_exceeded" not in reasons(evaluate_scenario(exact, specs, game_config))
    too_many = [*exact, make_step(transfer, Decimal("1000.00"))]
    assert "max_actions_exceeded" in reasons(
        evaluate_scenario(too_many, specs, game_config)
    )


def test_night_operation_boundaries(spec_by_code, specs, game_config) -> None:
    withdrawal = spec_by_code["cash_withdrawal"]
    salary = spec_by_code["salary"]
    night = {"time_of_day": "night"}
    two = [
        make_step(withdrawal, Decimal("5000.00"), context=night),
        make_step(salary, Decimal("10000.00"), context=night),
    ]
    assert "night_operations_exceeded" not in reasons(
        evaluate_scenario(two, specs, game_config)
    )
    three = [*two, make_step(withdrawal, Decimal("5000.00"), context=night)]
    assert "night_operations_exceeded" in reasons(
        evaluate_scenario(three, specs, game_config)
    )


def test_anonymous_recipient_count_and_amount_quotas(spec_by_code, specs, game_config) -> None:
    transfer = spec_by_code["card_transfer"]
    salary = spec_by_code["salary"]
    anonymous = {"recipient_type": "anonymous_wallet"}
    steps = [
        make_step(salary, Decimal("150000.00")),
        make_step(transfer, Decimal("40000.00"), context=anonymous),
        make_step(salary, Decimal("10000.00")),
        make_step(transfer, Decimal("30000.00"), context=anonymous),
    ]
    assert "category_limit_exceeded" not in reasons(
        evaluate_scenario(steps, specs, game_config)
    )
    steps[3] = make_step(transfer, Decimal("40000.00"), context=anonymous)
    snapshot = evaluate_scenario(steps, specs, game_config)
    assert "category_limit_exceeded" in reasons(snapshot)


def test_cash_quota_boundary(
    spec_by_code, specs, game_config
) -> None:
    deposit = spec_by_code["cash_deposit"]
    withdrawal = spec_by_code["cash_withdrawal"]

    over_cash = [
        make_step(deposit, Decimal("100000.00")),
        make_step(withdrawal, Decimal("60000.00")),
    ]
    assert "category_limit_exceeded" in reasons(
        evaluate_scenario(over_cash, specs, game_config)
    )



def test_resource_exhaustion_reports_the_right_field(spec_by_code, specs, game_config) -> None:
    transfer = spec_by_code["card_transfer"]
    snapshot = evaluate_scenario(
        [make_step(transfer, Decimal("500000.00"))], specs, game_config
    )
    assert "insufficient_balance" in reasons(snapshot)

    withdrawal = spec_by_code["cash_withdrawal"]
    salary = spec_by_code["salary"]
    heavy = [
        make_step(salary, Decimal("150000.00")),
        make_step(withdrawal, Decimal("10000.00"), frequency=4),
        make_step(salary, Decimal("10000.00")),
        make_step(withdrawal, Decimal("10000.00"), frequency=4),
    ]
    snapshot = evaluate_scenario(heavy, specs, game_config)
    assert "insufficient_energy" in reasons(snapshot)


def test_target_outflow_below_exact_and_above(spec_by_code, specs, game_config) -> None:
    salary = spec_by_code["salary"]
    transfer = spec_by_code["card_transfer"]

    below = evaluate_scenario(
        [make_step(salary, Decimal("150000.00")), make_step(transfer, Decimal("149999.99"))],
        specs,
        game_config,
    )
    assert below["objective"]["reached"] is False
    assert any(
        item["reason"] == "target_outflow_not_reached" for item in submit_blockers(below)
    )

    exact = evaluate_scenario(
        [make_step(salary, Decimal("150000.00")), make_step(transfer, Decimal("150000.00"))],
        specs,
        game_config,
    )
    assert exact["objective"]["reached"] is True
    assert exact["valid"] is True
    assert submit_blockers(exact) == []

    above = evaluate_scenario(
        [make_step(salary, Decimal("150000.00")), make_step(transfer, Decimal("160000.00"))],
        specs,
        game_config,
    )
    assert above["objective"]["reached"] is True


def test_empty_chain_is_valid_but_not_submittable(specs, game_config) -> None:
    snapshot = evaluate_scenario([], specs, game_config)
    assert snapshot["valid"] is True
    blockers = [item["reason"] for item in submit_blockers(snapshot)]
    assert "scenario_empty" in blockers
    assert "target_outflow_not_reached" in blockers


def test_several_simultaneous_violations_are_all_reported(
    spec_by_code, specs, game_config
) -> None:
    withdrawal = spec_by_code["cash_withdrawal"]
    salary = spec_by_code["salary"]
    steps = [
        make_step(withdrawal, Decimal("200000.00"), frequency=9, context={"time_of_day": "night"}),
        make_step(salary, Decimal("100000.00"), context={"time_of_day": "night"}),
        make_step(withdrawal, Decimal("100000.00"), context={"time_of_day": "night"}),
    ]
    snapshot = evaluate_scenario(steps, specs, game_config)
    found = set(reasons(snapshot))
    assert {"amount_out_of_range", "frequency_out_of_range"} <= found
    assert "night_operations_exceeded" in found
    assert snapshot["valid"] is False


def test_reordering_independent_steps_keeps_resource_totals(
    spec_by_code, specs, game_config
) -> None:
    salary = spec_by_code["salary"]
    withdrawal = spec_by_code["cash_withdrawal"]
    transfer = spec_by_code["card_transfer"]
    steps = [
        make_step(salary, Decimal("150000.00")),
        make_step(withdrawal, Decimal("100000.00")),
        make_step(transfer, Decimal("50000.00")),
    ]
    first = evaluate_scenario(steps, specs, game_config)
    swapped = evaluate_scenario([steps[0], steps[2], steps[1]], specs, game_config)
    assert first["totals"] == swapped["totals"]
    assert first["resources_after"]["balance"] == swapped["resources_after"]["balance"]


def test_step_ids_are_preserved_in_the_snapshot(spec_by_code, specs, game_config) -> None:
    salary = spec_by_code["salary"]
    step = make_step(salary, Decimal("50000.00"))
    snapshot = evaluate_scenario([step], specs, game_config)
    assert snapshot["per_step"][0]["step_id"] == step["step_id"]


def test_snapshot_is_deterministic(spec_by_code, specs, game_config) -> None:
    salary = spec_by_code["salary"]
    steps = [make_step(salary, Decimal("50000.00"), step_id="11111111-1111-1111-1111-111111111111")]
    assert evaluate_scenario(steps, specs, game_config) == evaluate_scenario(
        steps, specs, game_config
    )


def test_reference_config_is_the_documented_demo_round() -> None:
    assert REFERENCE_GAME_CONFIG["resources"]["initial_balance"] == "250000.00"
    assert REFERENCE_GAME_CONFIG["resources"]["initial_energy"] == 14
    assert REFERENCE_GAME_CONFIG["resources"]["initial_time"] == 18
    assert REFERENCE_GAME_CONFIG["objectives"]["max_actions"] == 8
    assert REFERENCE_GAME_CONFIG["objectives"]["target_outflow"] == "150000.00"


def test_snapshot_uses_only_the_current_resource_set(
    spec_by_code, specs, game_config
) -> None:
    salary = spec_by_code["salary"]
    snapshot = evaluate_scenario(
        [make_step(salary, Decimal("50000.00"))], specs, game_config
    )

    assert set(snapshot["resources_after"]) == {
        "balance",
        "energy",
        "time",
        "available_steps",
    }
    assert snapshot["resources_after"]["available_steps"] == 7
    assert set(snapshot["per_step"][0]["resources_before"]) == {
        "balance",
        "energy",
        "time",
    }
    assert set(snapshot["per_step"][0]["resources_after"]) == {
        "balance",
        "energy",
        "time",
    }


def test_risky_context_does_not_create_an_extra_resource_blocker(
    spec_by_code, specs, game_config
) -> None:
    from copy import deepcopy

    config = deepcopy(game_config)
    config["constraints"].update(
        max_identical_steps=3,
        max_night_operations=3,
        max_anonymous_operations=3,
        category_limits={},
    )
    steps = [
        make_step(
            spec_by_code["card_transfer"],
            Decimal("25000.00"),
            frequency=frequency,
            channel="web",
            context={
                "recipient_type": "anonymous_wallet",
                "time_of_day": "night",
                "velocity": "rapid",
                "has_documents": False,
            },
            action_details={
                "transfer_purpose": "no_purpose",
                "recipient_relationship": "unknown",
            },
        )
        for frequency in (2, 2, 3)
    ]
    snapshot = evaluate_scenario(steps, specs, config)
    assert snapshot["valid"] is True
    assert submit_blockers(snapshot) == []


# --------------------------------------------------------------------------
# Quotas
# --------------------------------------------------------------------------


def _with_anonymous_limit(config, limit="1000000.00"):
    return {
        **config,
        "constraints": {**config["constraints"], "category_limits": {"anonymous": limit}},
    }


def test_a_step_counts_once_against_a_quota_it_reaches_two_ways(
    spec_by_code, game_config
) -> None:
    """A card in the anonymous category, paid to an anonymous wallet.

    The card's own category and the recipient's used to be added separately, so
    the same turnover consumed the quota twice and the limit tripped at half the
    amount an organiser configured. No shipped card declares
    quota_category "anonymous", but `CardConfig` accepts it, so the editor can
    produce one.
    """
    card = replace(spec_by_code["card_transfer"], quota_category="anonymous")
    step = make_step(
        card, Decimal("10000.00"), context={"recipient_type": "anonymous_wallet"}
    )

    snapshot = evaluate_scenario([step], specs_by_key([card]), _with_anonymous_limit(game_config))

    assert snapshot["limit_usage"]["anonymous"] == "10000.00"


def test_a_step_still_counts_against_both_quotas_it_belongs_to(
    spec_by_code, game_config
) -> None:
    """Counting once per quota is not counting once overall."""
    card = replace(spec_by_code["card_transfer"], quota_category="cash")
    step = make_step(
        card, Decimal("10000.00"), context={"recipient_type": "anonymous_wallet"}
    )
    config = _with_anonymous_limit(game_config)
    config["constraints"]["category_limits"]["cash"] = "1000000.00"

    snapshot = evaluate_scenario([step], specs_by_key([card]), config)

    assert snapshot["limit_usage"]["anonymous"] == "10000.00"
    assert snapshot["limit_usage"]["cash"] == "10000.00"


def test_the_shipped_card_counts_the_recipient_quota_once(
    spec_by_code, specs, game_config
) -> None:
    """Control: card_transfer declares no category of its own."""
    step = make_step(
        spec_by_code["card_transfer"],
        Decimal("10000.00"),
        context={"recipient_type": "anonymous_wallet"},
    )

    snapshot = evaluate_scenario([step], specs, _with_anonymous_limit(game_config))

    assert snapshot["limit_usage"]["anonymous"] == "10000.00"
