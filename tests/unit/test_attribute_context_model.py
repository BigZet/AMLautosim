from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from scripts.aml_attribute_label_policy import interpretation_targets
from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import (
    extract_panel_features,
    views,
)


def relay():
    result = []
    for i in range(3):
        result.extend(
            [
                dict(
                    card={"code": "incoming_transfer"},
                    amount="10000",
                    sender_id="A",
                    action_details={
                        "incoming_kind": "bank_transfer",
                        "bank_country": "RU",
                    },
                    context={"channel": "bank"},
                    purpose_code="unknown",
                    interval_minutes=None if i == 0 else 60,
                ),
                dict(
                    card={"code": "card_transfer"},
                    amount="8800",
                    recipient_id="BCD"[i],
                    action_details={},
                    context={"channel": "mobile"},
                    purpose_code="unknown",
                    interval_minutes=1,
                ),
            ]
        )
    return result


def probability(steps):
    return interpretation_targets(
        views(pd.DataFrame([extract_panel_features(steps)]))
    ).mean()


@pytest.mark.parametrize("attribute", ["channel", "country", "kind", "purpose"])
def test_attributes_change_marginal_pattern_interpretation(attribute):
    steps = relay()
    changed = deepcopy(steps)
    if attribute == "channel":
        changed[3]["context"]["channel"] = "web"
    if attribute == "country":
        changed[2]["action_details"]["bank_country"] = "KG"
    if attribute == "kind":
        changed[2]["action_details"] = {"incoming_kind": "payment_service"}
    if attribute == "purpose":
        changed[3]["purpose_code"] = "refund"
    assert extract_panel_features(changed) != extract_panel_features(steps)
    assert probability(changed) > probability(steps)
    assert probability(changed) - probability(steps) < 0.13


def test_uniform_country_and_channel_renaming_is_invariant():
    steps = relay()
    changed = deepcopy(steps)
    for s in changed:
        if s["card"]["code"] == "incoming_transfer":
            s["action_details"]["bank_country"] = "KG"
        else:
            s["context"]["channel"] = "branch"
    assert extract_panel_features(changed) == extract_panel_features(steps)
    assert probability(changed) == probability(steps)


def test_incoming_purposes_and_purchase_purposes_are_observed():
    steps = relay()
    changed = deepcopy(steps)
    changed[2]["purpose_code"] = "loan"
    assert probability(changed) > probability(steps)
    # Purchase purpose is considered jointly with observable salary funding.
    steps += [
        dict(
            card={"code": "salary"},
            amount="10000",
            purpose_code="salary",
            action_details={"income_basis": "payroll_registry"},
            interval_minutes=1,
        ),
        dict(
            card={"code": "purchase"},
            amount="1000",
            purpose_code="unknown",
            interval_minutes=1,
        ),
    ]
    before = extract_panel_features(steps)
    steps[-1]["purpose_code"] = "personal_spending"
    assert (
        extract_panel_features(steps)["salary_consumption_share"]
        > before["salary_consumption_share"]
    )


def test_refund_cannot_reuse_a_receipt_or_erase_repeated_returns():
    steps = relay()
    for s in steps:
        if s["card"]["code"] == "card_transfer":
            s["recipient_id"] = "A"
            s["purpose_code"] = "refund"
    assert probability(steps) == 1
    single = steps[:2] + [deepcopy(steps[1])]
    f = extract_panel_features(single)
    assert f["supported_refund_share"] == pytest.approx(10000 / 17600)
    assert f["unsupported_refund_share"] == pytest.approx(7600 / 17600)


def test_context_alone_does_not_make_unstructured_activity_high():
    steps = relay()
    for s in steps:
        if s["card"]["code"] == "card_transfer":
            s["amount"] = "1000"
    steps[2]["action_details"]["bank_country"] = "KG"
    steps[3]["purpose_code"] = "refund"
    steps[3]["context"]["channel"] = "web"
    assert probability(steps) == 0


def test_vectorized_votes_match_independent_scalar_interpretations():
    x = views(pd.DataFrame([extract_panel_features(relay())]))
    expected = []
    for _, f in x.iterrows():
        shift = min(
            0.12,
            max(
                -0.12,
                0.06 * f.supported_refund_share
                + 0.04 * f.shared_expense_alignment
                + 0.04 * f.salary_consumption_share
                - 0.025 * f.rail_switch_rate
                - 0.02 * f.country_switch_rate
                - 0.02 * f.transfer_channel_switch_rate
                - 0.015 * f.cash_channel_switch_rate
                - 0.02 * f.purpose_switch_rate
                - 0.03 * f.unsupported_refund_share
                - 0.025 * f.service_relay_share
                - 0.025 * f.asset_cash_share
                - 0.02 * f.personal_passthrough_share
                - 0.015 * f.funding_diversity
                - 0.015 * f.cash_purpose_switch_rate,
            ),
        )
        votes = []
        for i in range(201):
            s = min(1, max(0, i / 200 + shift))
            votes.append(
                any(
                    (
                        f.second_match_error <= 0.20 - 0.16 * s,
                        f.fanout >= 2
                        and f.recipient_count >= 3
                        and f.precredit_outflow_share < 0.30 - 0.10 * s,
                        f.cash >= 1
                        and f.debit_episodes >= 2
                        and f.cash_share >= 0.15 + 0.15 * s,
                        f.sender_count >= (2 if s <= 2 / 3 else 3)
                        and f.max_recipient_share >= 0.72 + 0.20 * s
                        and f.precredit_outflow_share < 0.25 - 0.10 * s,
                        (
                            f.second_return_ratio_all
                            if s <= 2 / 3
                            else f.third_return_ratio_all
                        )
                        >= 0.45 + 0.15 * s,
                        f.card_count >= 7
                        and f.second_split_ratio_all <= 0.80 - 0.15 * s
                        and f.amount_repetition_strength >= 0.65 + 0.20 * s,
                    )
                )
            )
        expected.append(sum(votes) / 201)
    np.testing.assert_array_equal(interpretation_targets(x), expected)


def test_approved_twenty_case_limit_is_enforced_even_if_passed_flag_is_true():
    from src.aml_workshop_simulator.services.classifier_acceptance import (
        gameplay_accepted,
    )

    report = dict(
        passed=True,
        failures=[],
        seed_count=5000,
        counts={"valid": 1800},
        error_tolerance_policy=dict(
            approval="explicit_user_instruction",
            absolute_probability_error=0.25,
            maximum_chains_above_tolerance=20,
            actual_chains_above_tolerance=20,
        ),
        above_tolerance_cases=[dict(probability=0.8, target=0.4) for _ in range(20)],
    )
    assert gameplay_accepted(report, "hash")
    report["above_tolerance_cases"].append(dict(probability=0.8, target=0.4))
    report["error_tolerance_policy"]["actual_chains_above_tolerance"] = 21
    assert not gameplay_accepted(report, "hash")
