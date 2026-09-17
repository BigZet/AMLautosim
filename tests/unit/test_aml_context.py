from copy import deepcopy

import pytest

from tests.aml_context_support import context_fixture


def test_fact_budget_is_not_reused_and_directions_are_separate():
    from src.aml_workshop_simulator.services.aml_context import resolve_evidence

    config, steps = context_fixture()
    steps = steps[:4]
    steps[1]["amount"] = steps[2]["amount"] = "30000.00"
    rows = resolve_evidence(steps, config)
    assert [r["covered_credit_amount"] for r in rows] == ["80000.00", "0.00", "0.00", "20000.00"]
    assert [r["covered_debit_amount"] for r in rows] == ["0.00", "30000.00", "20000.00", "0.00"]


@pytest.mark.parametrize("status", ["unverified", "contradicted", "unknown"])
def test_only_verified_applicable_fact_covers_money(status):
    from src.aml_workshop_simulator.services.aml_context import resolve_evidence

    config, steps = context_fixture()
    config["behavior"]["aml_context"]["facts"][0]["verification_status"] = status
    row = resolve_evidence(steps[:1], config)[0]
    assert row["covered_credit_amount"] == "0.00"
    assert row["verification_status"] == status


def test_verified_fact_for_other_counterparty_is_a_mismatch():
    from src.aml_workshop_simulator.services.aml_context import resolve_evidence

    config, steps = context_fixture()
    steps[0]["sender_id"] = "B"
    row = resolve_evidence(steps[:1], config)[0]
    assert row["covered_credit_amount"] == "0.00"
    assert row["applicable"] is False
    assert row["mismatch"] is True
    assert row["contradicted"] is False  # Mismatch is not a finding that a document is false.


def test_future_evidence_cannot_change_observed_result():
    from src.aml_workshop_simulator.services.aml_context import resolve_evidence

    config, steps = context_fixture()
    config["behavior"]["aml_context"]["facts"][0]["available_at"] = "2026-09-14T09:00:00+03:00"
    row = resolve_evidence(steps[:1], config)[0]
    assert row["covered_credit_amount"] == "0.00"
    assert row["verification_status"] == "unknown"
    assert row["contradicted"] is False


def test_claim_must_exist_and_player_cannot_supply_verification():
    from src.aml_workshop_simulator.services.aml_context import canonical_steps

    config, steps = context_fixture()
    steps[0]["claim_id"] = "not-a-fact"
    with pytest.raises(ValueError, match="claim"):
        canonical_steps(steps, config)
    steps[0]["claim_id"] = "shared"
    steps[0]["verification_status"] = "verified"
    with pytest.raises(ValueError):
        canonical_steps(steps, config)


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-0.01"])
def test_nonfinite_or_negative_evidence_amount_rejected(invalid):
    from src.aml_workshop_simulator.services.aml_context import validate_context

    config, _ = context_fixture()
    ctx = config["behavior"]["aml_context"]
    ctx["facts"][0]["max_debit_amount"] = invalid
    with pytest.raises(ValueError):
        validate_context(ctx, config)


def test_naive_timestamps_and_duplicate_ids_are_rejected():
    from src.aml_workshop_simulator.services.aml_context import validate_context

    config, _ = context_fixture()
    ctx = config["behavior"]["aml_context"]
    ctx["facts"].append(deepcopy(ctx["facts"][0]))
    with pytest.raises(ValueError, match="unique"):
        validate_context(ctx, config)
    ctx["facts"].pop()
    ctx["as_of"] = "2026-09-13T09:00:00"
    with pytest.raises(ValueError):
        validate_context(ctx, config)


def test_incomplete_expected_range_is_rejected_but_exceeding_it_is_not():
    from src.aml_workshop_simulator.services.aml_context import validate_context, canonical_steps

    config, steps = context_fixture()
    ctx = config["behavior"]["aml_context"]
    ctx["expected_activity"]["expected_credit_min"] = None
    with pytest.raises(ValueError, match="range"):
        validate_context(ctx, config)
    ctx["expected_activity"]["expected_credit_min"] = "1000.00"
    ctx["expected_activity"]["expected_credit_max"] = "2000.00"
    assert len(canonical_steps(steps, config)) == len(steps)


def test_resource_projection_preserves_actual_engine_outcome():
    from src.aml_workshop_simulator.services.aml_context import evaluate, semantic_config, semantic_steps
    from src.aml_workshop_simulator.services.semantic_contract import evaluate as evaluate_v9

    config, steps = context_fixture()
    before = deepcopy((config, steps))
    result = evaluate(steps, config)
    expected = evaluate_v9(semantic_steps(steps), semantic_config(config))
    assert result == expected
    assert (config, steps) == before
