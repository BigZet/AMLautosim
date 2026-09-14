from copy import deepcopy

import pytest

from scripts.aml_dataset.core import (
    CONFIG,
    digest,
    frozen_config,
    label,
    mutate,
    normalize,
    read_json,
    read_jsonl,
    review_selection,
    split_rows,
)
from scripts.generate_aml_dataset import require_approval, run
from scripts.validate_aml_dataset import validate
from src.aml_workshop_simulator.services.aml_dataset_features import extract_features


@pytest.fixture(scope="module")
def review_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("aml") / "review"
    run("review", path)
    return path


def simple_steps(config):
    return normalize(
        [
            {"code": "incoming_transfer", "amount": 80000},
            {
                "code": "card_transfer",
                "amount": 40000,
                "context": {"velocity": "normal"},
            },
        ],
        config,
    )


def test_review_end_to_end(review_dir):
    result = validate(review_dir)
    assert result["rows"] == 48
    rows = read_jsonl(review_dir / "scenarios.jsonl")
    assert all(r["evaluation"]["can_submit"] for r in rows)
    assert all(r["features"]["card_incoming_transfer_count"] == 3 for r in rows)
    assert {r["features"]["income_basis"] for r in rows} == {
        "none",
        "payroll_registry",
        "service_contract",
        "no_reference",
    }
    assert read_json(review_dir / "coverage.json")["comparable_turnover_pairs"]


def test_review_reproducible(review_dir, tmp_path):
    other = tmp_path / "second"
    run("review", other)
    for filename in [
        "scenarios.jsonl",
        "challenge_blind.jsonl",
        "features.csv",
        "splits.csv",
        "counterfactual_pairs.jsonl",
    ]:
        assert (review_dir / filename).read_bytes() == (other / filename).read_bytes()


def test_mass_labeling_needs_actual_matching_review(review_dir, tmp_path):
    with pytest.raises(ValueError, match="review"):
        run("pilot", tmp_path / "pilot", review_dir)
    assert not (tmp_path / "pilot").exists()
    with pytest.raises(ValueError, match="reviewer"):
        require_approval(review_dir / "approval.json", {})


def test_risk_counterfactuals():
    config = frozen_config()
    rubric = read_json(CONFIG / "rubric.json")
    steps = simple_steps(config)

    def score(s):
        return label(extract_features(s, config), rubric)[0]

    base = score(steps)
    source = deepcopy(steps)
    source[0]["action_details"]["transfer_source"] = "crypto_exchange"
    assert score(source) == base
    night = deepcopy(steps)
    night[1]["context"]["time_of_day"] = "night"
    assert score(night) == base
    rapid = deepcopy(steps)
    rapid[1]["context"]["velocity"] = "rapid"
    assert score(rapid) > base
    salary = normalize([{"code": "salary", "amount": 25000}], config)
    assert score(rapid + salary) == score(rapid)
    assert score(list(reversed(rapid))) < score(rapid)


def test_feature_vector_does_not_contain_provenance_or_score():
    config = frozen_config()
    features = extract_features(simple_steps(config), config)
    assert not set(features) & {
        "target_risk_score",
        "baseline_risk_score",
        "family",
        "seed",
        "scenario_id",
        "can_submit",
        "violations",
    }
    assert "max_frequency_single_step" not in features
    assert "cash_inflow_sum" not in features


def test_shared_vectors_union_template_groups():
    rows = [
        {
            "scenario_id": str(i),
            "template_id": f"t{i}",
            "features": {"x": i},
            "target_risk_score": i,
        }
        for i in range(6)
    ]
    rows[1]["features"] = rows[0]["features"]
    split = split_rows(rows, 42)
    assert split[0]["group_id"] == split[1]["group_id"]
    assert split[0]["split"] == split[1]["split"]
    assert len({s["split"] for s in split}) == 3


def test_review_selection_has_120_distinct_records():
    rows = [
        {
            "scenario_id": str(i),
            "target_risk_score": i / 2,
            "baseline_risk_score": 100 - i / 2,
        }
        for i in range(200)
    ]
    selected = review_selection(rows)
    assert len({r["scenario_id"] for r in selected}) == 120
    assert sum(r["category"] == "risk_range" for r in selected) == 60
    assert sum(r["category"] == "boundary" for r in selected) == 30


def test_mutation_deterministic(review_dir):
    import random

    row = read_jsonl(review_dir / "scenarios.jsonl")[0]
    config = frozen_config()
    assert digest(mutate(row, random.Random(42), config)) == digest(
        mutate(row, random.Random(42), config)
    )


def test_validator_rejects_modified_export(review_dir, tmp_path):
    import shutil

    target = tmp_path / "tampered"
    shutil.copytree(review_dir, target)
    path = target / "labels.csv"
    path.write_text(path.read_text().replace("target_risk_score", "leaked_score"))
    with pytest.raises(ValueError, match="Artifact changed"):
        validate(target)


def test_pilot_pipeline_with_test_only_approval(review_dir, tmp_path, monkeypatch):
    """Exercise exports on 120 disposable fixtures, not the real 2,000-row pilot."""
    import scripts.generate_aml_dataset as cli
    from scripts.aml_dataset.core import write_json

    original_read = cli.read_json

    def test_settings(path):
        result = original_read(path)
        if path == CONFIG / "generation.json":
            result["pilot_samples"] = 120
        return result

    monkeypatch.setattr(cli, "read_json", test_settings)
    approved = read_json(review_dir / "approval.json")
    approved.update(status="approved", reviewer="automated-test-fixture-only")
    approval = tmp_path / "test-approval.json"
    write_json(approval, approved)
    output = tmp_path / "pilot-fixtures"
    cli.run("pilot", output, review_dir, approval)
    assert validate(output)["rows"] == 120
    from scripts.validate_aml_dataset import read_csv

    assert len(read_csv(output / "pilot_review.csv")) == 120
