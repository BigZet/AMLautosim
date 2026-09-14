from copy import deepcopy

from scripts.aml_dataset.expanded import label, rubric, extract_features
from scripts.check_expanded_balance import demo_config, demo_steps
import pytest


def test_intensive_flow_has_floor_without_limited_party_information():
    config = demo_config()
    features = extract_features(demo_steps(config), config)
    features.update(limited_information_amount_share=0, count_purchase=0, count_salary=0,
                    credit_debit_gap_10_60_excess_mean=0, matched_large_tempo_mean=1)
    score, terms = label(features, rubric())
    assert score >= 45
    assert any(t["name"] == "Интенсивная транзакционная активность" for t in terms)
    features["income_basis"] = "payroll_registry"
    features["count_salary"] = 1
    assert abs(label(features, rubric())[0] - score * .75) < .0001


def test_three_required_incoming_transfers_alone_get_no_activity_bonus():
    config = demo_config()
    steps = [s for s in demo_steps(config) if s["card"]["code"] == "incoming_transfer"]
    score, terms = label(extract_features(steps, config), rubric())
    assert score == 0
    assert not any(t["name"] == "Интенсивная транзакционная активность" for t in terms)


def test_small_isolated_flow_has_no_high_risk_floor():
    config = demo_config()
    steps = deepcopy(demo_steps(config)[:2])
    for s in steps:
        s["amount"] = "10000"
    assert label(extract_features(steps, config), rubric())[0] < 10


def test_exported_features_cannot_hide_label_conflicts():
    from scripts.aml_dataset.mass_release import check_projected_labels
    rows = [dict(features=dict(visible=1, omitted=0), target_risk_score=40),
            dict(features=dict(visible=1, omitted=1), target_risk_score=50)]
    with pytest.raises(ValueError, match="projection"):
        check_projected_labels(rows, ["visible"])
    check_projected_labels(rows, ["visible", "omitted"])
