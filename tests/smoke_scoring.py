from backend.app.domain.enums import RiskLabel
from backend.app.services.scoring import score_steps


def main() -> None:
    normal_score, normal_label, _ = score_steps(
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
    risky_score, risky_label, risky_explanation = score_steps(
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

    assert normal_score < 35, normal_score
    assert normal_label == RiskLabel.normal, normal_label
    assert risky_score >= 35, risky_score
    assert risky_label in {RiskLabel.review, RiskLabel.suspicious}, risky_label
    assert len(risky_explanation["top_factors"]) == 3
    print("scoring smoke ok")


if __name__ == "__main__":
    main()

