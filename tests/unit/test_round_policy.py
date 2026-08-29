"""The reduced parameter surface, as a round decides it.

Covers the four-operation contract: at most two editable parameters per
operation on top of amount and frequency, with stable server defaults for
everything else.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.aml_workshop_simulator.domain.catalog import (
    CARD_CATALOG,
    DEFAULT_OPERATION_CODES,
    build_parameter_schema,
    default_show_frequency,
    default_visible_params,
)
from src.aml_workshop_simulator.domain.round_policy import (
    MAX_VISIBLE_PARAMS,
    RoundPolicy,
    declared_params,
    operations_from_specs,
    split_param,
)
from src.aml_workshop_simulator.domain.rules import (
    REFERENCE_GAME_CONFIG,
    StructuralError,
    evaluate_scenario,
    reference_operations,
    validate_structure,
)
from tests.unit.conftest import make_step


def reasons(snapshot) -> list[str]:
    return [item["reason"] for item in snapshot["violations"]]


def policy_of(config, specs) -> RoundPolicy:
    return RoundPolicy.from_config(config, specs)


# --------------------------------------------------------------------------
# The default operation set
# --------------------------------------------------------------------------


def test_a_new_round_offers_exactly_four_operations() -> None:
    assert len(DEFAULT_OPERATION_CODES) == 4
    assert len(reference_operations()) == 4


def test_the_catalog_contains_only_the_default_operations() -> None:
    assert len(CARD_CATALOG) == 4
    assert {entry["code"] for entry in CARD_CATALOG} == set(DEFAULT_OPERATION_CODES)


def test_the_round_goal_is_reachable_with_the_four_operations(
    spec_by_code, specs, restricted_game_config
) -> None:
    """A single transfer already clears the 150 000 target from the start balance."""
    snapshot = evaluate_scenario(
        [make_step(spec_by_code["card_transfer"], Decimal("150000.00"))],
        specs,
        restricted_game_config,
    )
    assert snapshot["objective"]["reached"] is True
    assert snapshot["valid"] is True


@pytest.mark.parametrize(
    "quota_reason, code, context",
    [
        ("night_operations_exceeded", "salary", {"time_of_day": "night"}),
        (
            "anonymous_operations_exceeded",
            "card_transfer",
            {"recipient_type": "anonymous_wallet"},
        ),
    ],
)
def test_every_round_limit_stays_reachable_with_the_default_four(
    spec_by_code, specs, restricted_game_config, quota_reason, code, context
) -> None:
    """Each round-level counter still has an operation that can trigger it."""
    spec = spec_by_code[code]
    steps = [
        make_step(spec, spec.min_amount, context=context),
        make_step(spec_by_code["cash_deposit"], Decimal("5000.00")),
        make_step(spec, spec.min_amount, context=context),
        make_step(spec_by_code["cash_deposit"], Decimal("5000.00")),
        make_step(spec, spec.min_amount, context=context),
    ]
    snapshot = evaluate_scenario(steps, specs, restricted_game_config)
    assert quota_reason in reasons(snapshot)


# --------------------------------------------------------------------------
# Visible parameters
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", DEFAULT_OPERATION_CODES)
def test_each_operation_exposes_at_most_two_parameters(code: str) -> None:
    visible = default_visible_params(code)
    assert len(visible) <= MAX_VISIBLE_PARAMS
    assert visible[0] == "channel", "the channel matrix must stay playable"
    assert len(set(visible)) == len(visible)


@pytest.mark.parametrize("code", DEFAULT_OPERATION_CODES)
def test_visible_parameters_are_declared_by_the_card(code, spec_by_code) -> None:
    declared = set(declared_params(spec_by_code[code]))
    assert set(default_visible_params(code)) <= declared


def test_frequency_is_only_offered_where_repeats_are_a_move() -> None:
    structuring = {"cash_deposit", "card_transfer", "cash_withdrawal"}
    for code in DEFAULT_OPERATION_CODES:
        assert default_show_frequency(code) is (code in structuring), code


def test_the_card_contract_carries_the_defaults_to_the_database() -> None:
    for entry in CARD_CATALOG:
        schema = build_parameter_schema(entry)
        assert schema["default_visible_params"] == list(
            default_visible_params(entry["code"])
        )
        assert schema["default_show_frequency"] == default_show_frequency(entry["code"])


def test_split_param_covers_the_three_namespaces() -> None:
    assert split_param("channel") == ("channel", "channel")
    assert split_param("context.time_of_day") == ("context", "time_of_day")
    assert split_param("action.funds_source") == ("action", "funds_source")
    with pytest.raises(ValueError):
        split_param("nonsense.key")


# --------------------------------------------------------------------------
# The policy itself
# --------------------------------------------------------------------------


def test_policy_pins_every_parameter_it_does_not_expose(
    specs, restricted_game_config
) -> None:
    policy = policy_of(restricted_game_config, specs)
    operation = policy.for_card(("salary", 1))
    assert operation is not None
    assert operation.visible_params == ("channel", "context.time_of_day")
    # Everything else is pinned to a concrete, deterministic value.
    assert operation.pinned["context.has_documents"] is True
    assert operation.pinned["action.employer_profile"] == "verified_employer"
    assert operation.pinned["action.income_basis"] == "payroll_registry"


def test_a_legacy_config_hides_nothing(specs, game_config) -> None:
    policy = policy_of(game_config, specs)
    assert policy.legacy is True
    for key, spec in specs.items():
        operation = policy.for_card(key)
        assert operation is not None
        assert operation.visible_params == declared_params(spec)
        assert operation.pinned == {}


def test_an_operation_disabled_for_a_round_is_rejected(
    spec_by_code, specs, restricted_game_config
) -> None:
    config = dict(restricted_game_config)
    config["operations"] = [
        item for item in restricted_game_config["operations"]
        if item["code"] != "cash_withdrawal"
    ]
    steps = [make_step(spec_by_code["cash_withdrawal"], Decimal("5000.00"))]
    policy = policy_of(config, specs)
    violations = validate_structure(steps, specs, policy)
    assert [item.reason for item in violations] == ["card_not_in_round"]
    message = violations[0].message
    assert "отключена настройками" in message
    assert "salary" in message


def test_a_hidden_parameter_sent_with_another_value_is_a_422(
    spec_by_code, specs, restricted_game_config
) -> None:
    """A salary declares `has_documents` but the round does not expose it, so
    only the pinned value is legal."""
    step = make_step(
        spec_by_code["salary"], Decimal("50000.00"), context={"has_documents": False}
    )
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, restricted_game_config)
    violation = raised.value.violations[0]
    assert violation.reason == "parameter_not_editable"
    assert violation.field == "context.has_documents"
    assert violation.current == "False"
    assert violation.allowed == "True"
    assert "Есть подтверждающие документы" in violation.message


def test_a_context_field_the_card_never_declares_is_still_rejected(
    spec_by_code, specs, restricted_game_config
) -> None:
    """`velocity` is not part of the salary contract at all."""
    step = make_step(
        spec_by_code["salary"], Decimal("50000.00"), context={"velocity": "rapid"}
    )
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, restricted_game_config)
    assert raised.value.violations[0].reason == "context_field_not_applicable"


def test_a_hidden_action_detail_sent_with_another_value_is_a_422(
    spec_by_code, specs, restricted_game_config
) -> None:
    step = make_step(
        spec_by_code["salary"],
        Decimal("50000.00"),
        action_details={"employer_profile": "private_person"},
    )
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, restricted_game_config)
    violation = raised.value.violations[0]
    assert violation.reason == "parameter_not_editable"
    assert violation.field == "action_details.employer_profile"


def test_a_pinned_frequency_may_not_be_changed(
    spec_by_code, specs, restricted_game_config
) -> None:
    step = make_step(spec_by_code["salary"], Decimal("50000.00"), frequency=2)
    with pytest.raises(StructuralError) as raised:
        evaluate_scenario([step], specs, restricted_game_config)
    violation = raised.value.violations[0]
    assert violation.reason == "frequency_not_editable"
    assert violation.field == "frequency"
    assert violation.allowed == "1"


def test_a_visible_parameter_may_take_any_declared_option(
    spec_by_code, specs, restricted_game_config
) -> None:
    for value in ("day", "evening", "night"):
        step = make_step(
            spec_by_code["salary"], Decimal("50000.00"), context={"time_of_day": value}
        )
        snapshot = evaluate_scenario([step], specs, restricted_game_config)
        assert "parameter_not_editable" not in reasons(snapshot)


def test_a_visible_frequency_may_be_changed(
    spec_by_code, specs, restricted_game_config
) -> None:
    step = make_step(spec_by_code["cash_deposit"], Decimal("5000.00"), frequency=3)
    snapshot = evaluate_scenario([step], specs, restricted_game_config)
    assert "frequency_not_editable" not in reasons(snapshot)


# --------------------------------------------------------------------------
# Round overrides of card numbers
# --------------------------------------------------------------------------


def _config_with_override(base, code, **overrides):
    config = {key: value for key, value in base.items()}
    config["operations"] = [
        {**entry, **overrides} if entry["code"] == code else entry
        for entry in base["operations"]
    ]
    return config


def test_a_round_can_narrow_the_amount_range(
    spec_by_code, specs, restricted_game_config
) -> None:
    config = _config_with_override(
        restricted_game_config, "card_transfer", max_amount="20000.00"
    )
    snapshot = evaluate_scenario(
        [make_step(spec_by_code["card_transfer"], Decimal("30000.00"))], specs, config
    )
    assert "amount_out_of_range" in reasons(snapshot)
    ok = evaluate_scenario(
        [make_step(spec_by_code["card_transfer"], Decimal("20000.00"))], specs, config
    )
    assert "amount_out_of_range" not in reasons(ok)


def test_a_round_can_re_tune_resource_costs(
    spec_by_code, specs, restricted_game_config
) -> None:
    expensive = _config_with_override(
        restricted_game_config, "card_transfer", energy_cost=20
    )
    snapshot = evaluate_scenario(
        [make_step(spec_by_code["card_transfer"], Decimal("10000.00"))],
        specs,
        expensive,
    )
    assert "insufficient_energy" in reasons(snapshot)


def test_operations_from_specs_produces_a_valid_default_block(specs) -> None:
    block = operations_from_specs(list(specs.values()), DEFAULT_OPERATION_CODES)
    assert {item["code"] for item in block} == set(DEFAULT_OPERATION_CODES)
    for entry in block:
        assert len(entry["visible_params"]) <= MAX_VISIBLE_PARAMS


# --------------------------------------------------------------------------
# Snapshot shape the participant UI relies on
# --------------------------------------------------------------------------


def test_the_snapshot_reports_resources_before_and_after_each_step(
    spec_by_code, specs, restricted_game_config
) -> None:
    steps = [
        make_step(spec_by_code["salary"], Decimal("100000.00")),
        make_step(spec_by_code["card_transfer"], Decimal("50000.00")),
    ]
    snapshot = evaluate_scenario(steps, specs, restricted_game_config)
    first, second = snapshot["per_step"]
    assert first["resources_before"]["balance"] == "250000.00"
    assert first["resources_after"]["balance"] == "350000.00"
    assert second["resources_before"] == first["resources_after"]
    assert first["card_title"] == "Получить зарплату"


def test_the_snapshot_reports_every_limit_with_its_remainder(
    spec_by_code, specs, restricted_game_config
) -> None:
    snapshot = evaluate_scenario(
        [make_step(spec_by_code["cash_deposit"], Decimal("50000.00"))],
        specs,
        restricted_game_config,
    )
    limits = {item["code"]: item for item in snapshot["limits"]}
    assert limits["cash"]["used"] == "50000.00"
    assert limits["cash"]["remaining"] == "100000.00"
    assert limits["actions"]["used"] == "1"
    assert limits["actions"]["remaining"] == str(
        REFERENCE_GAME_CONFIG["objectives"]["max_actions"] - 1
    )
    assert limits["night_operations"]["limit"] == "2"
