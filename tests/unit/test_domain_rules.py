from __future__ import annotations

import pytest
from decimal import Decimal

from src.aml_workshop_simulator.services.catboost_features import (
    extract_catboost_features,
    get_catboost_feature_names,
    get_catboost_categorical_feature_names,
)
from src.aml_workshop_simulator.services.scenario_service import (
    calculate_resource_snapshot,
    calculate_resource_score,
)
from src.aml_workshop_simulator.services.scoring import score_steps
from src.aml_workshop_simulator.core.enums import RiskLabel


def test_catboost_feature_extraction_empty() -> None:
    features = extract_catboost_features([])
    assert features["num_steps"] == 0
    assert features["total_turnover"] == 0.0
    assert features["has_crypto"] == 0
    assert features["primary_channel"] == "none"


def test_catboost_feature_extraction_steps() -> None:
    steps = [{"card_code": "salary",
              "amount": 100000.0,
              "frequency": 1,
              "context": {"channel": "bank",
                          "country_risk": "low",
                          "recipient_type": "known_counterparty",
                          "time_of_day": "day",
                          "velocity": "spaced",
                          "has_documents": True},
              },
             {"card_code": "crypto_exchange",
              "amount": 80000.0,
              "frequency": 1,
              "context": {"channel": "exchange",
                          "country_risk": "high",
                          "recipient_type": "anonymous_wallet",
                          "time_of_day": "night",
                          "velocity": "rapid",
                          "has_documents": False},
              },
             ]
    features = extract_catboost_features(steps)
    assert features["num_steps"] == 2
    assert features["total_turnover"] == 180000.0
    assert features["total_inflow"] == 100000.0
    assert features["total_outflow"] == 80000.0
    assert features["has_crypto"] == 1
    assert features["high_risk_country_turnover"] == 80000.0
    assert features["night_operations_count"] == 1
    assert features["rapid_velocity_count"] == 1
    assert features["without_docs_large_sum"] == 80000.0


def test_resource_calculation_limits_and_violations() -> None:
    # 1. Valid steps reaching goal
    steps = [{"card_code": "salary",
              "amount": 100000,
              "frequency": 1,
              "context": {"channel": "bank",
                           "has_documents": True}},
             {"card_code": "card_transfer",
              "amount": 75000,
              "frequency": 2,
              "context": {"channel": "mobile",
                           "has_documents": True}},
             ]
    snapshot = calculate_resource_snapshot(steps)
    assert snapshot["valid"] is True
    assert snapshot["goal_reached"] is True
    assert float(snapshot["totals"]["gross_outflow"]) == 150000.0
    assert len(snapshot["violations"]) == 0

    # 2. Too many steps violation
    too_many_steps = [{"card_code": "online_purchase",
                       "amount": 1000, "frequency": 1}] * 9
    bad_snapshot = calculate_resource_snapshot(too_many_steps)
    assert bad_snapshot["valid"] is False
    assert any("не больше 8" in v for v in bad_snapshot["violations"])


def test_scoring_rules_and_labels() -> None:
    # Low risk retail steps
    low_risk_steps = [{"card_code": "salary",
                       "amount": 50000,
                       "frequency": 1,
                       "context": {"channel": "bank",
                                    "time_of_day": "day",
                                    "velocity": "spaced",
                                    "has_documents": True}},
                      {"card_code": "online_purchase",
                       "amount": 20000,
                       "frequency": 1,
                       "context": {"channel": "web",
                                   "time_of_day": "day",
                                   "velocity": "normal",
                                   "has_documents": True}},
                      ]
    score, label, explanation = score_steps(low_risk_steps)
    assert label == RiskLabel.normal
    assert score < 35.0
    assert "catboost_features_payload" in explanation

    # High risk suspicious steps (Cash deposit + Anonymous crypto + Night +
    # Rapid velocity)
    high_risk_steps = [{"card_code": "cash_deposit",
                        "amount": 100000,
                        "frequency": 1,
                        "context": {"channel": "atm",
                                     "time_of_day": "night",
                                     "velocity": "rapid",
                                     "has_documents": False}},
                       {"card_code": "crypto_exchange",
                        "amount": 95000,
                        "frequency": 1,
                        "context": {"channel": "exchange",
                                    "country_risk": "high",
                                    "recipient_type": "anonymous_wallet",
                                    "time_of_day": "night",
                                    "velocity": "rapid",
                                    "has_documents": False}},
                       ]
    h_score, h_label, h_exp = score_steps(high_risk_steps)
    assert h_label == RiskLabel.suspicious
    assert h_score >= 50.0
