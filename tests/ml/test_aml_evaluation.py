import numpy as np
import pytest


def test_probability_metrics_respect_unrounded_boundaries_and_weights():
    from scripts.evaluate_aml_classifier import probability_metrics

    result = probability_metrics(
        [0, 0, 1, 1], [0.09999, 0.1, 0.89999, 0.9], [1, 1, 1, 1]
    )
    assert result["grey"] == 0.5
    assert result["false_high"] == 0
    assert result["false_low"] == 0
    assert result["precision_high"] == 1
    assert result["npv_low"] == 1
    weighted = probability_metrics([0, 0, 1, 1], [0.95, 0.05, 0.95, 0.05], [1, 9, 1, 9])
    assert weighted["false_high"] == pytest.approx(0.1)
    assert weighted["false_low"] == pytest.approx(0.9)


def test_group_event_bound_does_not_claim_zero_risk_from_zero_errors():
    from scripts.evaluate_aml_classifier import group_event_bound

    assert group_event_bound(0, 30) == pytest.approx(1 - 0.05 ** (1 / 30))
    assert group_event_bound(30, 30) == 1
    assert group_event_bound(0, 0) is None


def test_small_perfect_sample_fails_support_despite_collapsed_bootstrap():
    from scripts.evaluate_aml_classifier import evaluate_probabilities

    report = evaluate_probabilities(
        [0, 1] * 4,
        [0.01, 0.99] * 4,
        [f"g{i}" for i in range(4) for _ in range(2)],
        prior=0.5,
        bootstrap_repeats=20,
    )
    assert not report["release_ready"]
    assert report["group_events"]["false_high"]["upper_95"] > 0.1
    assert not report["gates"]["test_class_group_support"]
    assert not report["gates"]["bootstrap_protocol"]
    assert (
        report["aggregations"]["row"]["confidence_intervals"]["false_high"]["upper"]
        == 0
    )


def test_large_perfect_group_fixture_passes_prespecified_quantitative_gates():
    from scripts.evaluate_aml_classifier import evaluate_probabilities

    report = evaluate_probabilities(
        [0, 1] * 120,
        [0.01, 0.99] * 120,
        [f"g{i}" for i in range(120) for _ in range(2)],
        prior=0.5,
    )
    assert report["release_ready"]
    assert all(report["gates"].values())
    assert report["bootstrap"]["repeats"] == 2000
    assert all(a["metrics"]["roc_auc"] == 1 for a in report["aggregations"].values())
    assert report["reliability"][0]["groups"] == 120
    assert report["reliability"][-1]["groups"] == 120
    from src.aml_workshop_simulator.services.aml_release_validation import (
        validate_main_test,
    )

    validate_main_test(report)
    from copy import deepcopy

    forged = deepcopy(report)
    for value in forged["aggregations"].values():
        value["constant_prior"]["brier"] = 100
        value["constant_prior"]["log_loss"] = 100
        value["metrics"]["brier"] = 50
        value["metrics"]["log_loss"] = 50
    with pytest.raises(ValueError):
        validate_main_test(forged)
    report["aggregations"]["row"]["metrics"]["ece"] = 0.5
    with pytest.raises(ValueError, match="point metric"):
        validate_main_test(report)


def test_inclusive_metric_gate_handles_float_sum_at_exact_threshold():
    from scripts.evaluate_aml_classifier import evaluate_probabilities

    report = evaluate_probabilities(
        [0, 1] * 120,
        [0.05, 0.95] * 120,
        [f"g{i}" for i in range(120) for _ in range(2)],
        prior=0.5,
        bootstrap_repeats=2,
    )
    assert report["gates"]["row:ece"]
    assert report["gates"]["group:ece"]


@pytest.mark.parametrize(
    "labels,p,groups",
    [
        ([0, 1], [0.1, np.nan], ["a", "b"]),
        ([0, 2], [0.1, 0.9], ["a", "b"]),
        ([0, 1], [0.1, 1.1], ["a", "b"]),
        ([0, 1], [0.1, 0.9], ["a"]),
        ([0, 1], [0.1, 0.9], ["", "b"]),
    ],
)
def test_invalid_evaluation_inputs_reject(labels, p, groups):
    from scripts.evaluate_aml_classifier import evaluate_probabilities

    with pytest.raises(ValueError):
        evaluate_probabilities(labels, p, groups, prior=0.5)


def test_subgroup_support_and_both_weighted_confident_errors_control_allowlist():
    from scripts.evaluate_aml_classifier import evaluate_subgroups

    y = [0, 1] * 60
    p = [0.01, 0.99] * 60
    groups = [f"g{i}" for i in range(60) for _ in range(2)]
    dimensions = {
        "profile": ["supported"] * 120,
        "channel": [
            ["bank_transfer", "rare_channel"] if i < 10 else ["bank_transfer"]
            for i in range(120)
        ],
    }
    report = evaluate_subgroups(y, p, groups, dimensions)
    assert report["passed"]
    assert report["allowlist"] == {
        "profile": ["supported"],
        "channel": ["bank_transfer"],
    }
    rare = next(s for s in report["slices"] if s["value"] == "rare_channel")
    assert rare["status"] == "insufficient-support"
    assert rare["groups_with_class_0"] == 5
    p[:40] = [0.99, 0.01] * 20
    report = evaluate_subgroups(y, p, groups, dimensions)
    assert not report["passed"]
    assert report["allowlist"]["profile"] == []


def test_test_access_receipt_allows_exact_reproduction_but_not_another_candidate(
    tmp_path,
):
    from scripts.evaluate_aml_classifier import claim_test_access

    first = claim_test_access("dataset-hash", "candidate-a", tmp_path)
    assert first["reproduction"] is False
    repeated = claim_test_access("dataset-hash", "candidate-a", tmp_path)
    assert repeated["reproduction"] is True
    with pytest.raises(ValueError, match="already opened"):
        claim_test_access("dataset-hash", "candidate-b", tmp_path)
