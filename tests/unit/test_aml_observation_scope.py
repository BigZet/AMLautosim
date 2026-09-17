from datetime import datetime

import pytest

from tests.aml_context_support import context_fixture
from src.aml_workshop_simulator.services.aml_context import validate_config, BehaviorV10
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features
from src.aml_workshop_simulator.services.profile_history import history_summary


def partial_fixture():
    config, steps = context_fixture()
    config["behavior"]["history"]["operations"] = []
    config["behavior"]["aml_context"].update(
        history_coverage="partial", history_start="2026-09-12T09:00:00+03:00",
        history_end="2026-09-13T09:00:00+03:00",
    )
    return config, steps


def test_partial_history_cannot_claim_complete_absence():
    config, steps = partial_fixture()
    summary = history_summary(BehaviorV10.model_validate(config["behavior"]))
    assert summary.starts_at == datetime.fromisoformat("2026-09-12T09:00:00+03:00")
    assert summary.model_dump()["coverage"] == "partial"
    assert all(p.observation == "unknown" for p in summary.counterparties)
    assert all(p.activity is None for p in summary.counterparties)
    features = extract_features(steps, config)
    assert features["history_empty"] == 0
    assert features["unobserved_recipient_share"] == 0
    assert features["historical_recipient_comparison_applicable"] == 0


def test_history_event_outside_claimed_fragment_is_invalid():
    config, _ = partial_fixture()
    config["behavior"]["history"]["operations"] = [{
        "id":"outside", "occurred_at":"2026-09-11T09:00:00+03:00",
        "operation_code":"card_transfer", "amount":"100.00",
        "counterparty_id":"A", "category":None,
    }]
    with pytest.raises(ValueError, match="coverage"):
        validate_config(config)


def test_fact_cutoff_cannot_precede_available_history():
    config, _ = context_fixture()
    config["behavior"]["aml_context"]["as_of"] = "2026-09-10T09:00:00+03:00"
    with pytest.raises(ValueError, match="as_of"):
        validate_config(config)


def test_v10_cannot_hide_future_history_in_unversioned_legacy_shape():
    from src.aml_workshop_simulator.schemas.round_config import parse_game_config

    config, _ = context_fixture()
    config["behavior"].pop("release", None)
    config["behavior"]["history"].pop("version", None)
    config["behavior"]["aml_context"].update(history_coverage="unknown", history_start=None, history_end=None)
    config["behavior"]["history"]["operations"][1]["occurred_at"] = "2027-01-01T09:00:00+03:00"
    with pytest.raises(ValueError):
        validate_config(config)
    config["config_version"] = "test"
    with pytest.raises(ValueError):
        parse_game_config(config, stored=True)


def test_unknown_coverage_cannot_supply_observed_events():
    config, _ = context_fixture()
    config["behavior"]["aml_context"].update(history_coverage="unknown", history_start=None, history_end=None)
    with pytest.raises(ValueError, match="Unknown coverage"):
        validate_config(config)


def test_cash_history_does_not_set_card_transfer_baseline():
    config, steps = context_fixture()
    config["behavior"]["history"]["operations"] = [{
        "id":"cash", "occurred_at":"2026-09-12T09:00:00+03:00",
        "operation_code":"cash_withdrawal", "amount":"100.00",
        "counterparty_id":None, "category":None,
    }]
    features = extract_features(steps, config)
    assert "debit_mean_history_ratio" not in features
    assert features["card_transfer_history_comparable"] == 0
    assert features["card_transfer_mean_history_ratio"] == 0
    assert features["cash_withdrawal_history_comparable"] == 1
    assert features["cash_withdrawal_mean_history_ratio"] == 100


def test_purpose_expectation_outside_period_is_not_a_mismatch():
    config, steps = context_fixture()
    activity = config["behavior"]["aml_context"]["expected_activity"]
    activity.update(period_start="2026-09-14T00:00:00+03:00", period_end="2026-09-15T00:00:00+03:00", activity_kinds=["unknown"])
    features = extract_features(steps, config)
    assert features["activity_purpose_mismatch_share"] == 0
    assert features["activity_purpose_comparable_share"] == 0


def test_zero_expected_volume_has_finite_explicit_excess():
    config, steps = context_fixture()
    activity = config["behavior"]["aml_context"]["expected_activity"]
    activity.update(period_start="2026-09-13T09:00:00+03:00", period_end="2026-09-13T09:08:00+03:00", expected_credit_min="0.00", expected_credit_max="0.00")
    features = extract_features(steps, config)
    assert features["expected_volume_comparable"] == 1
    assert features["expected_credit_excess_ratio_applicable"] == 0
    assert features["expected_credit_excess_ratio"] == 0
    assert features["expected_credit_excess_amount"] == 230000
