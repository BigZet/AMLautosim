from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.counterparty_support import step
from tests.purchase_support import purchase_config
from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
    score_expanded_scenario,
)
from src.aml_workshop_simulator.schemas.round_config import parse_game_config
from src.aml_workshop_simulator.services.scoring_service import _evaluate
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy


def buy(config, amount="1000.00"):
    value = step(config, "purchase", "shop")
    value["amount"] = amount
    return value


@pytest.mark.parametrize("amount", ["1000.00", "20000.00"])
def test_purchase_bounds_balance_fees_and_no_goal(amount):
    config = purchase_config()
    result = evaluate_expanded_scenario([buy(config, amount)], config)
    assert result["valid"]
    assert (
        result["resources_after"]["balance"]
        == f"{Decimal('180000') - Decimal(amount):.2f}"
    )
    assert result["resources_after"]["energy"] == 29
    assert result["resources_after"]["time"] == 29
    assert result["totals"] == dict(
        gross_inflow="0.00",
        gross_outflow=amount,
        fees="0.00",
        target_outflow="0.00",
        purchase_outflow=amount,
    )
    assert result["per_step"][0]["purchase"] == dict(
        merchant_id="shop", category="groceries"
    )
    blocker = next(
        v
        for v in submit_blockers(result)
        if v["reason"] == "target_outflow_not_reached"
    )
    assert blocker["current"] == "0.00"
    assert not result["objective"]["reached"]


@pytest.mark.parametrize("amount", ["999.99", "20000.01"])
def test_out_of_range_rejected(amount):
    config = purchase_config()
    with pytest.raises(ValidationFailed):
        evaluate_expanded_scenario([buy(config, amount)], config)


def mixed_purchases(config, amounts):
    result = []
    for index, amount in enumerate(amounts):
        if index:
            result.append(step(config))
        result.append(buy(config, amount))
    return result


def test_total_and_count_independent_limits():
    config = purchase_config()
    result = evaluate_expanded_scenario(
        mixed_purchases(config, ["10000.00"] * 3), config
    )
    assert result["valid"]
    assert result["totals"]["purchase_outflow"] == "30000.00"
    assert (
        next(limit for limit in result["limits"] if limit["code"] == "purchase_count")[
            "used"
        ]
        == "3"
    )
    above = evaluate_expanded_scenario(
        mixed_purchases(config, ["10000.00", "10000.00", "10000.01"]), config
    )
    assert not above["valid"]
    assert any(v["reason"] == "purchase_total_exceeded" for v in above["violations"])
    fourth = evaluate_expanded_scenario(
        mixed_purchases(config, ["1000.00"] * 4), config
    )
    assert not fourth["valid"]
    assert (
        next(limit for limit in fourth["limits"] if limit["code"] == "purchase_count")[
            "used"
        ]
        == "4"
    )
    assert any(
        v["current"] == "4" and v["allowed"] == "3" for v in fourth["violations"]
    )


def test_insufficient_funds_and_income_before_purchase():
    config = purchase_config()
    config["resources"]["initial_balance"] = "1000.00"
    value = buy(config, "2000.00")
    bad = evaluate_expanded_scenario([value], config)
    assert any(v["reason"] == "insufficient_balance" for v in bad["violations"])
    good = evaluate_expanded_scenario([step(config), value], config)
    assert good["valid"]
    assert good["resources_after"]["balance"] == "9000.00"
    value["interval_minutes"] = 1440
    waited = evaluate_expanded_scenario([step(config), value], config)
    assert waited["per_step"][1]["time_cost"] == 5
    assert waited["per_step"][1]["fee"] == "0.00"


@pytest.mark.parametrize(
    "change",
    [
        {"recipient_id": "A"},
        {"sender_id": "A"},
        {"category": "groceries"},
        {"action_details": {"category": "groceries"}},
    ],
)
def test_merchant_category_is_server_owned(change):
    config = purchase_config()
    value = buy(config)
    value.update(change)
    with pytest.raises(ValidationFailed):
        evaluate_expanded_scenario([value], config)


def test_policy_and_fixed_card_cannot_be_bypassed():
    config = purchase_config()
    config["behavior"]["purchases"] = None
    with pytest.raises(ValidationFailed):
        evaluate_expanded_scenario([buy(config)], config)
    config = purchase_config()
    config["operations"][-1]["max_occurrences"] = 4
    data = deepcopy(config)
    data.pop("card_snapshots")
    with pytest.raises(ValidationError):
        parse_game_config(data)
    with pytest.raises(ValidationFailed):
        evaluate_expanded_scenario([buy(config)], config)
    config = purchase_config()
    config["behavior"]["purchases"] = {}
    assert evaluate_expanded_scenario([buy(config)], config)["valid"]


def test_purchase_does_not_dilute_risk_or_add_protective_factors():
    config = purchase_config()
    values = [step(config), step(config, "card_transfer")]
    base = score_expanded_scenario(values, config)
    purchase = buy(config)
    purchase["interval_minutes"] = 1440
    actual = score_expanded_scenario(values + [purchase], config)
    assert actual == base
    assert actual["explanation"]["step_count"] == 2
    assert not any(
        f["step_id"] == purchase["step_id"]
        for f in actual["explanation"]["all_factors"]
    )
    only = score_expanded_scenario([purchase], config)
    assert only["risk_score"] == 0
    assert not evaluate_expanded_scenario([purchase], config)["objective"]["reached"]


def test_gap_between_financial_operations_survives_purchase_filtering():
    config = purchase_config()
    values = [step(config), buy(config), step(config, "card_transfer")]
    values[-1]["interval_minutes"] = 60
    result = score_expanded_scenario(values, config)
    assert not any(
        f["code"] == "sequence:rapid_turnover"
        for f in result["explanation"]["all_factors"]
    )


def test_preview_and_scoring_use_same_totals_and_snapshot():
    from scripts.check_expanded_balance import demo_config, demo_steps
    from src.aml_workshop_simulator.services.game_classifier import get_game_classifier, game_config

    config = demo_config()
    config.update(game_config())
    config["risk_model"] = get_game_classifier().identity
    values = demo_steps(config, "purchase")
    preview = evaluate_expanded_scenario(values, config)
    specs = snapshot_specs(config)
    result, _ = _evaluate(values, specs, config, RoundPolicy.from_config(config, specs))
    assert result == preview
    assert result["totals"]["gross_outflow"] == "401000.00"
    assert result["totals"]["target_outflow"] == "400000.00"
