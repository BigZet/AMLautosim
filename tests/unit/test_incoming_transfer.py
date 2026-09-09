"""Incoming provenance, quota accounting, features and strict card boundaries."""

from itertools import product

import pytest

from scripts.check_game_balance import play
from scripts.generate_catboost_sample_data import generate_synthetic_scenarios
from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import (
    StructuralError,
    card_spec_from_catalog,
)
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.simulation import evaluate_scenario
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn
from src.aml_workshop_simulator.services.catboost_features import (
    extract_catboost_features,
    get_catboost_feature_names,
)
from src.aml_workshop_simulator.services.scenario_service import canonical_steps

SOURCES = ["domestic_bank", "foreign_bank_kg", "crypto_exchange", "payment_service"]
SENDERS = ["anonymous_established_account", "regular_sender", "anonymous_new_account"]


def canonical_incoming(source="domestic_bank", sender="regular_sender"):
    specs = {
        s.key: s
        for i, c in enumerate(CARD_CATALOG, 1)
        if (s := card_spec_from_catalog(c, i))
    }
    spec = specs[("incoming_transfer", 1)]
    config = base_game_config()
    inputs = [
        ScenarioStepIn.model_validate(
            {
                "step_id": "00000000-0000-0000-0000-000000000001",
                "card": {"id": spec.id, "code": spec.code, "version": spec.version},
                "amount": "80000.00",
                "action_details": {
                    "transfer_source": source,
                    "sender_relationship": sender,
                },
            }
        )
    ]
    return (
        canonical_steps(inputs, specs, RoundPolicy.from_config(config, specs)),
        specs,
        config,
    )


@pytest.mark.parametrize("source,sender", list(product(SOURCES, SENDERS)))
def test_all_incoming_profiles_credit_balance_without_using_cash_quota(source, sender):
    snapshot, risk, _ = play(
        [("incoming_transfer", 80000)],
        transfer_source=source,
        sender_relationship=sender,
    )
    assert snapshot["valid"]
    assert snapshot["resources_after"]["balance"] == "260000.00"
    assert snapshot["totals"]["gross_outflow"] == "0.00"
    assert snapshot["limit_usage"]["cash"] == "0.00"
    assert not snapshot["objective"]["reached"]
    codes = {f["code"] for f in risk["explanation"]["all_factors"]}
    assert f"detail:incoming_transfer:transfer_source:{source}" in codes
    assert f"detail:incoming_transfer:sender_relationship:{sender}" in codes


def test_sources_have_distinct_costs_and_risk():
    domestic, domestic_risk, _ = play([("incoming_transfer", 80000)])
    foreign, foreign_risk, _ = play(
        [("incoming_transfer", 80000)], transfer_source="foreign_bank_kg"
    )
    crypto, crypto_risk, _ = play(
        [("incoming_transfer", 80000)], transfer_source="crypto_exchange"
    )
    assert domestic["per_step"][0]["time_cost"] == 4
    assert foreign["per_step"][0]["time_cost"] == 5
    assert crypto["per_step"][0]["time_cost"] == 3
    assert domestic["per_step"][0]["energy_cost"] == 3
    assert (
        foreign["per_step"][0]["energy_cost"]
        == crypto["per_step"][0]["energy_cost"]
        == 4
    )
    assert (
        domestic_risk["risk_score"]
        < foreign_risk["risk_score"]
        < crypto_risk["risk_score"]
    )


@pytest.mark.parametrize(
    "defect,reason",
    [
        ("old_code", "unknown_card_version"),
        ("old_field", "unknown_action_parameter"),
        ("old_value", "invalid_action_parameter"),
        ("missing_source", "missing_action_parameter"),
        ("atm", "channel_not_allowed"),
    ],
)
def test_old_cash_contract_is_not_accepted_by_new_round(defect, reason):
    steps, specs, config = canonical_incoming()
    if defect == "old_code":
        steps[0]["card"]["code"] = "cash_deposit"
    elif defect == "old_field":
        steps[0]["action_details"]["funds_source"] = "unexplained"
    elif defect == "old_value":
        steps[0]["action_details"]["transfer_source"] = "documented_savings"
    elif defect == "missing_source":
        del steps[0]["action_details"]["transfer_source"]
    else:
        steps[0]["context"]["channel"] = "atm"
    with pytest.raises(StructuralError) as exc:
        evaluate_scenario(steps, specs, config)
    assert reason in {v.reason for v in exc.value.violations}


def test_new_source_features_do_not_report_cash_and_respect_frozen_defaults():
    steps, _, config = canonical_incoming(
        "crypto_exchange", "anonymous_established_account"
    )
    features = extract_catboost_features(steps, config)
    assert features["incoming_transfer_sum"] == 80000
    assert features["crypto_exchange_inflow_sum"] == 80000
    assert features["cash_inflow_sum"] == features["has_cash"] == 0
    assert features["primary_incoming_source"] == "crypto_exchange"
    assert features["primary_sender_relationship"] == "anonymous_established_account"
    assert set(features) == set(get_catboost_feature_names())
    operation = next(
        o for o in config["operations"] if o["code"] == "incoming_transfer"
    )
    operation["visible_params"] = []
    operation["defaults"] = {
        "action.transfer_source": "foreign_bank_kg",
        "action.sender_relationship": "anonymous_new_account",
    }
    steps[0]["action_details"] = {}
    features = extract_catboost_features(steps, config)
    assert features["foreign_bank_inflow_sum"] == 80000
    assert features["primary_sender_relationship"] == "anonymous_new_account"


def test_synthetic_examples_are_reproducible_and_use_current_sources():
    samples = generate_synthetic_scenarios()
    assert samples == generate_synthetic_scenarios()
    sources = set()
    for sample in samples:
        assert "evaluation" in sample
        for step in sample["steps"]:
            ScenarioStepIn.model_validate(step)
            assert step["card"]["code"] != "cash_deposit"
            if step["card"]["code"] == "incoming_transfer":
                sources.add(step["action_details"]["transfer_source"])
    assert sources == set(SOURCES)


def test_sender_profiles_change_risk_without_changing_recipient_quota():
    scores = {}
    for sender in SENDERS:
        snapshot, risk, _ = play(
            [("incoming_transfer", 80000)], sender_relationship=sender
        )
        scores[sender] = risk["risk_score"]
        assert snapshot["valid"]
        assert snapshot["limit_usage"]["anonymous"] == "0.00"
        assert snapshot["limit_usage"]["anonymous_operations"] == 0
        expected_time = 5 if sender == "anonymous_established_account" else 4
        assert snapshot["per_step"][0]["time_cost"] == expected_time
    assert (
        scores["regular_sender"]
        < scores["anonymous_established_account"]
        < scores["anonymous_new_account"]
    )


@pytest.mark.parametrize("sender", ["own_account", "family", "customer", "unrelated"])
def test_superseded_sender_profiles_are_rejected(sender):
    steps, specs, config = canonical_incoming(sender=sender)
    with pytest.raises(StructuralError) as exc:
        evaluate_scenario(steps, specs, config)
    assert "invalid_action_parameter" in {v.reason for v in exc.value.violations}
