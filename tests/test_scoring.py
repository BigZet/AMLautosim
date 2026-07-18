from backend.app.domain.enums import RiskLabel
from backend.app.services.scoring import score_steps


def test_low_risk_scenario_scores_as_normal():
    score, label, explanation = score_steps(
        [
            {
                "card_code": "salary_transfer",
                "amount": 20_000,
                "frequency": 1,
                "country_risk": "low",
                "recipient_type": "known_counterparty",
            }
        ],
        {"salary_transfer": 2},
    )

    assert score < 35
    assert label == RiskLabel.normal
    assert len(explanation["top_factors"]) == 3


def test_structuring_scenario_scores_as_review_or_suspicious():
    score, label, explanation = score_steps(
        [
            {
                "card_code": "split_transfer",
                "amount": 95_000,
                "frequency": 4,
                "country_risk": "medium",
                "recipient_type": "new_counterparty",
            }
        ],
        {"split_transfer": 24},
    )

    assert score >= 35
    assert label in {RiskLabel.review, RiskLabel.suspicious}
    assert explanation["top_factors"][0]["points"] >= explanation["top_factors"][-1]["points"]


def test_risk_context_and_protective_factors_are_explained():
    base = {
        "card_code": "card_transfer",
        "amount": 100_000,
        "frequency": 1,
        "country_risk": "low",
        "recipient_type": "known_counterparty",
        "channel": "branch",
        "time_of_day": "day",
        "velocity": "spaced",
        "has_documents": True,
    }
    risky = {
        **base,
        "country_risk": "high",
        "recipient_type": "anonymous_wallet",
        "channel": "web",
        "time_of_day": "night",
        "velocity": "rapid",
        "has_documents": False,
    }

    safe_score, _, safe_explanation = score_steps([base], {"card_transfer": 5})
    risky_score, _, risky_explanation = score_steps([risky], {"card_transfer": 5})

    assert risky_score > safe_score
    assert safe_explanation["protective_factors"]
    assert any(
        factor["name"] == "documents" for factor in safe_explanation["protective_factors"]
    )
    assert any(
        factor["name"] == "time_of_day:night" for factor in risky_explanation["all_factors"]
    )


def test_sequence_patterns_are_included_in_explanation():
    _, _, explanation = score_steps(
        [
            {
                "card_code": "cash_deposit",
                "amount": 100_000,
                "frequency": 1,
                "country_risk": "low",
                "recipient_type": "known_counterparty",
            },
            {
                "card_code": "crypto_exchange",
                "amount": 100_000,
                "frequency": 1,
                "country_risk": "medium",
                "recipient_type": "new_counterparty",
            },
        ],
        {"cash_deposit": 12, "crypto_exchange": 20},
    )

    names = {factor["name"] for factor in explanation["all_factors"]}
    assert "sequence:cash_to_high_risk" in names
    assert "sequence:rapid_turnover" in names
