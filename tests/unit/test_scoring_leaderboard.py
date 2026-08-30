"""Risk engine (`risk-rules-v2`) and leaderboard formula (`leaderboard-v2`)."""

from __future__ import annotations

import copy
from decimal import Decimal

from src.aml_workshop_simulator.core.enums import RiskLabel
from src.aml_workshop_simulator.domain.rules import evaluate_scenario
from src.aml_workshop_simulator.domain.scoring import (
    leaderboard_scores,
    resource_score,
    score_scenario,
    weights_sum_to_one,
)
from tests.unit.conftest import make_step


def chain(spec_by_code, **overrides):
    salary = spec_by_code["salary"]
    withdrawal = spec_by_code["cash_withdrawal"]
    transfer = spec_by_code["card_transfer"]
    return [
        make_step(salary, Decimal("120000.00"), channel="bank"),
        make_step(withdrawal, Decimal("100000.00"), channel="atm", **overrides),
        make_step(transfer, Decimal("60000.00"), channel="mobile"),
    ]


def test_same_input_gives_the_same_result(spec_by_code, specs, game_config) -> None:
    steps = chain(spec_by_code)
    first = score_scenario(steps, specs, game_config)
    second = score_scenario(copy.deepcopy(steps), specs, game_config)
    assert first["risk_score"] == second["risk_score"]
    assert first["explanation"]["all_factors"] == second["explanation"]["all_factors"]


def test_scores_are_clamped_to_the_zero_hundred_range(spec_by_code, specs, game_config) -> None:
    transfer = spec_by_code["card_transfer"]
    hostile = [
        make_step(
            transfer,
            Decimal("100000.00"),
            frequency=5,
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
    ]
    result = score_scenario(hostile, specs, game_config)
    assert Decimal(0) <= result["risk_score"] <= Decimal(100)
    assert result["risk_label"] == RiskLabel.suspicious


def test_factor_points_sum_matches_the_raw_score(spec_by_code, specs, game_config) -> None:
    result = score_scenario(chain(spec_by_code), specs, game_config)
    explanation = result["explanation"]
    total = sum(Decimal(item["points"]) for item in explanation["all_factors"])
    assert str(total) == explanation["raw_score"]


def test_protective_factors_are_reported_separately(spec_by_code, specs, game_config) -> None:
    result = score_scenario(chain(spec_by_code), specs, game_config)
    explanation = result["explanation"]
    assert explanation["protective_factors"], "documents/known counterparty must protect"
    assert all(Decimal(item["points"]) < 0 for item in explanation["protective_factors"])
    assert all(Decimal(item["points"]) > 0 for item in explanation["top_risk_factors"])


def test_top_factors_are_sorted_deterministically(spec_by_code, specs, game_config) -> None:
    result = score_scenario(chain(spec_by_code), specs, game_config)
    points = [Decimal(item["points"]) for item in result["explanation"]["top_risk_factors"]]
    assert points == sorted(points, reverse=True)


def test_thresholds_come_from_the_round_snapshot(spec_by_code, specs, game_config) -> None:
    steps = chain(spec_by_code)
    strict = copy.deepcopy(game_config)
    strict["scoring"] = {
        "version": "risk-rules-v2",
        "review_threshold": "0.00",
        "suspicious_threshold": "0.01",
    }
    assert score_scenario(steps, specs, strict)["risk_label"] == RiskLabel.suspicious
    lenient = copy.deepcopy(game_config)
    lenient["scoring"] = {
        "version": "risk-rules-v2",
        "review_threshold": "99.00",
        "suspicious_threshold": "99.50",
    }
    assert score_scenario(steps, specs, lenient)["risk_label"] == RiskLabel.normal


def test_sequence_factor_is_produced_for_rapid_cash_out(
    spec_by_code, specs, game_config
) -> None:
    deposit = spec_by_code["cash_deposit"]
    withdrawal = spec_by_code["cash_withdrawal"]
    steps = [
        make_step(deposit, Decimal("100000.00"), channel="atm"),
        make_step(withdrawal, Decimal("90000.00"), channel="atm"),
    ]
    codes = {item["code"] for item in score_scenario(steps, specs, game_config)["explanation"]["sequence_factors"]}
    assert "sequence:rapid_turnover" in codes


def test_reordering_independent_steps_only_changes_sequence_factors(
    spec_by_code, specs, game_config
) -> None:
    salary = spec_by_code["salary"]
    withdrawal = spec_by_code["cash_withdrawal"]
    a = make_step(salary, Decimal("50000.00"))
    b = make_step(withdrawal, Decimal("20000.00"))
    forward = score_scenario([a, b], specs, game_config)
    backward = score_scenario([b, a], specs, game_config)
    non_sequence = lambda result: sorted(  # noqa: E731
        (item["code"], item["points"])
        for item in result["explanation"]["all_factors"]
        if item["category"] != "sequence"
    )
    assert non_sequence(forward) == non_sequence(backward)


def test_resource_score_components_and_weights(spec_by_code, specs, game_config) -> None:
    snapshot = evaluate_scenario(chain(spec_by_code), specs, game_config)
    score = resource_score(snapshot, game_config)
    assert Decimal(0) <= score <= Decimal(100)
    assert weights_sum_to_one(game_config)


def test_full_resources_score_one_hundred(specs, game_config) -> None:
    snapshot = evaluate_scenario([], specs, game_config)
    assert resource_score(snapshot, game_config) == Decimal("100.00")
    assert resource_score(snapshot, None) == Decimal("100.00")


def test_available_steps_are_the_only_step_budget_component(specs, game_config) -> None:
    config = copy.deepcopy(game_config)
    config["leaderboard"]["resource_weights"] = {
        "balance": "0",
        "energy": "0",
        "time": "0",
        "fees": "0",
        "available_steps": "1",
    }
    snapshot = evaluate_scenario([], specs, config)
    snapshot["resources_after"]["available_steps"] = 4
    assert resource_score(snapshot, config) == Decimal("50.00")


def test_a_cheaper_chain_scores_at_least_as_well(spec_by_code, specs, game_config) -> None:
    salary = spec_by_code["salary"]
    transfer = spec_by_code["card_transfer"]
    frugal = [
        make_step(salary, Decimal("150000.00")),
        make_step(transfer, Decimal("150000.00")),
    ]
    wasteful = [
        make_step(salary, Decimal("150000.00")),
        make_step(transfer, Decimal("150000.00")),
        make_step(spec_by_code["card_transfer"], Decimal("50000.00")),
    ]
    frugal_score = resource_score(evaluate_scenario(frugal, specs, game_config), game_config)
    wasteful_score = resource_score(
        evaluate_scenario(wasteful, specs, game_config), game_config
    )
    assert frugal_score >= wasteful_score


def test_game_score_is_monotonic_in_risk_and_resources(game_config) -> None:
    low_risk = leaderboard_scores(Decimal("10.00"), Decimal("80.00"), game_config)
    high_risk = leaderboard_scores(Decimal("40.00"), Decimal("80.00"), game_config)
    assert low_risk["game_score"] > high_risk["game_score"]

    rich = leaderboard_scores(Decimal("20.00"), Decimal("90.00"), game_config)
    poor = leaderboard_scores(Decimal("20.00"), Decimal("50.00"), game_config)
    assert rich["game_score"] > poor["game_score"]


def test_stealth_is_one_hundred_minus_risk(game_config) -> None:
    scores = leaderboard_scores(Decimal("42.50"), Decimal("78.20"), game_config)
    assert scores["stealth_score"] == Decimal("57.50")
    # 0.60 * 57.50 + 0.40 * 78.20 = 65.78
    assert scores["game_score"] == Decimal("65.78")


def test_weights_validation_rejects_a_broken_config(game_config) -> None:
    broken = copy.deepcopy(game_config)
    broken["leaderboard"]["weights"] = {"stealth": "0.70", "resources": "0.40"}
    assert weights_sum_to_one(broken) is False


def test_explanation_carries_the_disclaimer(spec_by_code, specs, game_config) -> None:
    result = score_scenario(chain(spec_by_code), specs, game_config)
    assert "не является AML-решением" in result["explanation"]["disclaimer"]
