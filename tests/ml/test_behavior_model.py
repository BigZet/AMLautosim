from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from scripts.aml_dataset.behavior_training import build_groups, topology, packet
from scripts.check_expanded_balance import demo_config, demo_steps
from scripts.behavior_model import weights, pair_errors
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import extract_features


def test_group_partition_is_disjoint_with_zero_cash_support():
    groups = build_groups(2026091501, set())
    assert len(groups) == 144 and len({g["shape"] for g in groups}) == 144
    for split in ("validation", "test"):
        for n in (5, 6, 7):
            assert any(
                g["split"] == split
                and g["debit_count"] == n
                and "DDD" not in g["shape"]
                for g in groups
            )
    assert all("CCC" not in g["shape"] for g in groups)


def test_features_observe_salary_without_reading_rubric():
    config = demo_config()
    steps = demo_steps(config)
    baseline = extract_features(steps, config)
    card = next(c for c in config["card_snapshots"] if c["code"] == "salary")
    extra = {
        "step_id": "00000000-0000-0000-0000-000000000020",
        "card": {k: card[k] for k in ["id", "code", "version"]},
        "amount": "20000",
        "sender_id": "employer",
        "recipient_id": None,
        "action_details": {"income_basis": "payroll_registry"},
        "context": {},
        "interval_minutes": 1,
    }
    after = extract_features(steps + [extra], config)
    assert baseline["salary_present"] == 0 and after["salary_present"] == 1
    assert (
        after["salary_payroll_registry_present"] == 1
        and after["salary_service_contract_present"] == 0
    )
    assert after["salary_total"] == 20000
    assert after["salary_credit_share"] == pytest.approx(20000 / 250000)
    assert (
        after["transfer_sufficient_amount_share"]
        == baseline["transfer_sufficient_amount_share"]
    )
    assert topology(steps) == topology(steps + [extra])
    renamed = deepcopy(config)
    renamed["behavior"]["profile"]["description"] = "Irrelevant story"
    assert extract_features(steps + [extra], renamed) == after


def test_balancing_assigns_equal_total_weight_to_each_observed_cell():
    x = pd.DataFrame(
        {
            "income_basis": ["absent"] * 10 + ["payroll_registry"] * 2,
            "count_cash_withdrawal": [0] * 12,
        }
    )
    w = weights(x)
    assert w.mean() == pytest.approx(1)
    assert w[:10].sum() == pytest.approx(w[10:].sum())


def test_pair_evaluation_measures_magnitude_not_only_sign():
    data = {
        "pairs": [
            dict(
                group="g", split="test", kind="salary", before="a", after="b", a=0, b=1
            )
        ],
        "y": np.array([80, 60]),
    }
    result, _ = pair_errors(data, np.array([80, 79]), "test")
    assert result["salary"]["direction_rate"] == 1
    assert result["salary"]["delta_mae"] == 19


def test_generator_reads_card_channels_and_keeps_parent_for_salary_variants():
    import random

    config = demo_config()
    cards = {c["code"]: c for c in config["card_snapshots"]}
    parent = next(
        g
        for g in build_groups(2026091501, set())
        if g["debit_count"] == 5 and "DDD" not in g["shape"]
    )
    for i in range(300):
        result = packet(random.Random(i), parent, config, cards, 0)
        if result:
            _, members = result
            assert {kind for kind, _ in members} >= {
                "base",
                "payroll_registry",
                "service_contract",
                "no_reference",
            }
            assert all(topology(steps) == parent["shape"] for _, steps in members)
            for _, steps in members:
                for s in steps:
                    if "channel" in s["context"]:
                        assert (
                            s["context"]["channel"]
                            in cards[s["card"]["code"]]["channels"]
                        )
            return
    pytest.fail("No valid sample")


def test_contract_signature_accepts_serialized_defaults_but_rejects_cost_changes():
    from src.aml_workshop_simulator.services.aml_risk_model import contract_signature

    original = demo_config()
    serialized = deepcopy(original)
    serialized["card_snapshots"].reverse()
    for card in serialized["card_snapshots"]:
        card["title"] = "Display name"
        for field in card["fields"] + card["context_fields"]:
            field.setdefault("required", True)
            for option in field.get("options", []):
                for key in ("risk_points", "time_cost", "energy_cost"):
                    option.setdefault(key, 0)
    assert contract_signature(original) == contract_signature(serialized)
    salary = next(c for c in serialized["card_snapshots"] if c["code"] == "salary")
    salary["fields"][0]["options"][0]["time_cost"] += 1
    assert contract_signature(original) != contract_signature(serialized)
