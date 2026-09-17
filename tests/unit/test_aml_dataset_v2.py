from copy import deepcopy
import json
import subprocess
import sys

import pytest

from scripts.aml_dataset.expanded import (
    build,
    validate,
    write_package,
    fingerprint,
    label,
    rubric,
    stable,
)
from scripts.validate_expanded_aml_dataset import validate_directory
from src.aml_workshop_simulator.services.aml_dataset_features_v2 import extract_features


@pytest.fixture(scope="module")
def package():
    return build()


def test_review_passes_and_reproduces(package, tmp_path):
    assert stable(package) == stable(build())
    report = validate(package)
    assert report["references"] == 48 and report["blind"] == 24 and report["pairs"] == 7
    destination = tmp_path / "review"
    write_package(package, destination)
    assert validate_directory(destination) == report
    with pytest.raises(FileExistsError):
        write_package(package, destination)


def test_duplicate_and_forged_label_fail(package):
    modified = deepcopy(package)
    modified["references"][1] = deepcopy(modified["references"][0])
    with pytest.raises(AssertionError):
        validate(modified)
    modified = deepcopy(package)
    modified["references"][0]["target_risk_score"] += 1
    with pytest.raises(AssertionError):
        validate(modified)


@pytest.mark.parametrize("tamper", ["label", "features"])
def test_optimized_package_validation_rejects_tampering(package, tmp_path, tamper):
    modified = deepcopy(package)
    row = modified["references"][0]
    if tamper == "label":
        row["target_risk_score"] += 1
    else:
        row["features"]["num_steps"] += 1
    source = tmp_path / "package.json"
    source.write_text(stable(modified), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "import json, sys; from pathlib import Path; "
            "from scripts.aml_dataset.expanded import validate; "
            "validate(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))",
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, result.stdout
    assert "AssertionError" in result.stderr


@pytest.mark.parametrize("tamper", [None, "package_hash", "csv_label"])
def test_optimized_directory_validation_checks_saved_artifacts(
    package, tmp_path, tamper
):
    destination = tmp_path / "review"
    write_package(package, destination)
    if tamper == "package_hash":
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["package_hash"] = "forged-hash"
        manifest_path.write_text(json.dumps(manifest))
    elif tamper == "csv_label":
        import csv

        csv_path = destination / "features.csv"
        with csv_path.open(newline="") as file:
            reader = csv.DictReader(file)
            fields = reader.fieldnames
            rows = list(reader)
        rows[0]["target_risk_score"] = str(float(rows[0]["target_risk_score"]) + 1)
        with csv_path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-m",
            "scripts.validate_expanded_aml_dataset",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if tamper is None:
        assert result.returncode == 0, result.stderr
        assert "technical_review_passed_not_approved" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert "AssertionError" in result.stderr


def test_final_recipient_novelty_weight_is_nine(package):
    rules = rubric()
    term = next(t for t in rules["terms"] if t["feature"] == "unobserved_recipient_share")
    assert term["weight"] == 9
    features = dict(package["references"][0]["features"],
                    target_outflow=400000, count_card_transfer=5,
                    credit_debit_links=2, unobserved_recipient_share=1)
    explanation = label(features, rules)[1]
    assert next(t["contribution"] for t in explanation
                if t["name"] == term["name"]) == 9


def test_waiting_is_bounded_continuous_and_preserves_context(package):
    rules = rubric()
    for row in package["references"]:
        features = dict(row["features"])
        features["credit_debit_gap_mean"] = 1
        features["credit_debit_gap_10_60_excess_mean"] = 0
        features["matched_large_tempo_mean"] = 1
        baseline = label(features, rules)[0]
        previous = baseline
        for gap in (10, 11, 35, 60, 1440):
            features["credit_debit_gap_mean"] = gap
            features["credit_debit_gap_10_60_excess_mean"] = min(50, max(0, gap - 10))
            score, terms = label(features, rules)
            assert baseline * .85 - .0001 <= score <= previous + .0001
            assert score == pytest.approx(sum(t["contribution"] for t in terms), abs=.000051)
            if gap == 11:
                assert baseline - score <= baseline * .003 + .0001
            previous = score
        if features["credit_debit_links"]:
            assert previous == pytest.approx(baseline * .85, abs=.0001)
        features["credit_debit_links"] = 0
        slow = label(features, rules)[0]
        features["credit_debit_gap_mean"] = 1
        features["credit_debit_gap_10_60_excess_mean"] = 0
        features["matched_large_tempo_mean"] = 1
        assert label(features, rules)[0] == slow


def test_recipient_rules_are_small_and_single_return_is_neutral():
    from scripts.check_expanded_balance import demo_config, demo_steps

    config = demo_config()
    steps = demo_steps(config)
    features = extract_features(steps, config)
    assert features["observed_return_cycle_count"] == 2
    # Repeated debits after one credit are one observed cycle, not many.
    assert extract_features(steps[:3], config)["observed_return_cycle_count"] == 1
    rules = rubric()
    for cycles, expected in ((0, 0), (1, 0), (2, 2), (3, 4), (10, 4)):
        changed = dict(features, observed_return_cycle_count=cycles, matched_large_episode_count=0)
        terms = label(changed, rules)[1]
        assert next(t["contribution"] for t in terms if t["name"] == "Matched flow and returns") == expected
    for recipients, expected in ((1, 0), (3, 0), (4, 1.5), (5, 3), (20, 3)):
        terms = label(dict(features, unique_recipients=recipients), rules)[1]
        assert next(t["contribution"] for t in terms if t["name"] == "Более трёх получателей") == expected
    for ratio, expected in ((1, 0), (2, 0), (3, 1), (5, 3), (100, 3)):
        terms = label(dict(features, history_has_debits=1, debit_mean_history_ratio=ratio), rules)[1]
        assert next(t["contribution"] for t in terms if t["name"] == "Небольшой рост сумм") == expected
    assert features["comparable_historical_recipient_share"] == 0
    history = config["behavior"]["history"]["operations"]
    event = dict(history[1], operation_code="card_transfer", amount="78000.00")
    history.append(dict(event, id="repeat1"))
    assert extract_features(steps, config)["comparable_historical_recipient_share"] == 0
    history.append(dict(event, id="repeat2", occurred_at="2026-09-01T23:00:00+03:00"))
    assert extract_features(steps, config)["comparable_historical_recipient_share"] == 0
    # Different encoded dates are still the same calendar day in the round zone.
    history[-1]["occurred_at"] = "2026-08-31T23:30:00+00:00"
    assert extract_features(steps, config)["comparable_historical_recipient_share"] == 0
    history[-1]["occurred_at"] = "2026-09-05T09:00:00+03:00"
    familiar = extract_features(steps, config)
    assert familiar["comparable_historical_recipient_share"] == 1
    assert next(t["contribution"] for t in label(familiar, rules)[1]
                if t["name"] == "Сопоставимые исторические переводы") == -3
    for event in history[-2:]:
        event["amount"] = "1000.00"
    assert extract_features(steps, config)["comparable_historical_recipient_share"] == 0


def test_one_long_wait_cannot_replace_other_waits():
    from scripts.check_expanded_balance import demo_config, demo_steps

    config = demo_config()
    steps = demo_steps(config)
    rules = rubric()
    baseline = label(extract_features(steps, config), rules)[0]
    for interval in (60, 1440):
        changed = deepcopy(steps)
        changed[1]["interval_minutes"] = interval
        features = extract_features(changed, config)
        assert features["credit_debit_links"] == 3
        assert features["credit_debit_gap_10_60_excess_mean"] == pytest.approx(50 / 3)
        assert baseline * .85 - .0001 <= label(features, rules)[0] < baseline
    for index in (1, 4, 7):
        steps[index]["interval_minutes"] = 60
    assert label(extract_features(steps, config), rules)[0] == pytest.approx(
        baseline * .85, abs=.0001
    )


def test_observations_ignore_id_renaming_and_labels_ignore_provenance(package):
    config = deepcopy(package["config"])
    steps = deepcopy(package["references"][0]["steps"])
    before = fingerprint(steps, config)
    features = extract_features(steps, config)
    for p in config["behavior"]["counterparties"]:
        p["id"] = "renamed-" + p["id"]
    config["behavior"]["counterparties"].reverse()
    config["behavior"]["profile"]["id"] = "another-profile-id"
    for e in config["behavior"]["history"]["operations"]:
        e["id"] = "renamed-" + e["id"]
        if e["counterparty_id"]:
            e["counterparty_id"] = "renamed-" + e["counterparty_id"]
    for s in steps:
        for key in ("sender_id", "recipient_id"):
            if s.get(key):
                s[key] = "renamed-" + s[key]
    assert fingerprint(steps, config) == before
    assert extract_features(steps, config) == features
    assert label({**features, "family": "any", "seed": 99}, rubric()) == label(
        features, rubric()
    )


def test_mass_generation_refuses_before_review(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.generate_expanded_aml_dataset",
            "--stage",
            "pilot",
            "--output",
            str(tmp_path / "pilot"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "review is pending" in result.stderr
    assert not (tmp_path / "pilot").exists()


def test_purchase_source_unchanged_and_salary_reduces_risk(package):
    for pair in package["pairs"]:
        if pair["kind"] == "source":
            assert (
                pair["before"]["target_risk_score"]
                == pair["after"]["target_risk_score"]
            )
        if pair["kind"] == "salary":
            assert (
                pair["after"]["target_risk_score"] < pair["before"]["target_risk_score"]
            )
            assert (
                pair["before"]["resources"]["energy"]
                - pair["after"]["resources"]["energy"]
                == 8
            )
            assert (
                pair["before"]["resources"]["time"] - pair["after"]["resources"]["time"]
                == 9
            )


def test_context_coverage_and_history_do_not_spend_current_resources(package):
    features = [r["features"] for r in package["references"]]
    assert {f["history_known"] for f in features} == {0, 1}
    assert {f["history_empty"] for f in features} == {0, 1}
    assert {f["history_debit_mean"] for f in features} >= {0, 2000, 65000}
    assert {f["interval_max"] for f in features} == {1, 10, 60, 1440}
    assert any(f["night_share"] > 0 for f in features)
    assert any(f["channel_branch_count"] > 0 for f in features)
    assert any(f["channel_web_count"] > 0 for f in features)
    from src.aml_workshop_simulator.services.expanded_simulation import (
        evaluate_expanded_scenario,
    )

    r = package["references"][2]
    empty = deepcopy(r["config_snapshot"])
    empty["behavior"]["history"]["operations"] = []
    assert (
        evaluate_expanded_scenario(r["steps"], empty)["resources_after"]
        == r["resources"]
    )


def test_joint_review_cannot_be_satisfied_by_changing_status_only(package, tmp_path):
    import json
    from scripts.aml_dataset.joint_review import check_joint_review

    path = tmp_path / "review"
    write_package(package, path)
    with pytest.raises(ValueError, match="pending"):
        check_joint_review(path)
    decision = json.loads((path / "review-decision.json").read_text())
    decision.update(
        status="approved",
        rubric_accepted=True,
        reviewer="test-only",
        reviewed_at="2026-09-14T12:00:00+03:00",
        user_decision_evidence="Synthetic unit test, not actual approval",
    )
    (path / "review-decision.json").write_text(json.dumps(decision))
    with pytest.raises(ValueError, match="Human decision missing"):
        check_joint_review(path)


def test_constants_are_selected_without_validation_or_blind(package):
    report = validate(package)
    training = [r for r in package["references"] if r["group"] == "five-transfers"]
    assert report["constant_features"] == sorted(
        k
        for k in training[0]["features"]
        if len({r["features"][k] for r in training}) == 1
    )
    assert all(
        "family" not in r["features"] and "config_snapshot" not in r["features"]
        for r in package["references"]
    )


def test_mass_gate_precedes_sampling(package, tmp_path, monkeypatch):
    from scripts.aml_dataset import mass_release

    path = tmp_path / "review"
    write_package(package, path)

    def must_not_sample(*args, **kwargs):
        raise AssertionError("No sampling before human review")

    monkeypatch.setattr(mass_release, "candidates", must_not_sample)
    with pytest.raises(ValueError, match="pending"):
        mass_release.generate_mass(path, tmp_path / "pilot", "pilot")
    assert not (tmp_path / "pilot").exists()


def test_bounded_candidate_sampling_is_reproducible_and_keeps_lineage(package):
    from scripts.aml_dataset.mass_release import candidates

    rows, rejected = candidates(package["references"], 12, 190)
    assert len(rows) == 12
    assert stable((rows, rejected)) == stable(
        candidates(package["references"], 12, 190)
    )
    assert len({r["observable_hash"] for r in rows}) == 12
    assert all(r["features"]["count_card_transfer"] != 7 for r in rows)
    assert all(r["group"] in {p["group"] for p in package["references"]} for r in rows)


def test_pilot_review_selection_has_60_30_30_distinct_records():
    from collections import Counter
    from scripts.aml_dataset.mass_release import review_sample

    rows = [
        dict(
            id=f"T{i:04}",
            target_risk_score=i / 20,
            baseline={"risk_score": str((i % 10) * 10)},
        )
        for i in range(2000)
    ]
    sample = review_sample(rows)
    assert Counter(r["reason"] for r in sample) == {
        "risk_range": 60,
        "boundary": 30,
        "baseline_disagreement": 30,
    }
    assert len({r["record"]["id"] for r in sample}) == 120
    assert sample == review_sample(rows)


def test_human_review_requires_matching_version_and_independent_blind_scores(
    package, tmp_path
):
    import csv
    import json
    from scripts.aml_dataset.joint_review import check_joint_review, FIELDS

    path = tmp_path / "review"
    write_package(package, path)
    decision = json.loads((path / "review-decision.json").read_text())
    decision.update(
        status="approved",
        rubric_accepted=True,
        reviewer="test-only",
        reviewed_at="2026-09-14T12:00:00+03:00",
        user_decision_evidence="Temporary synthetic unit test only",
    )
    (path / "review-decision.json").write_text(json.dumps(decision))
    with (path / "reference-decisions.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(
            dict(
                id=r["id"],
                observable_hash=r["observable_hash"],
                decision="accept",
                reviewed_score=r["target_risk_score"],
                reason="Synthetic test fixture",
            )
            for r in package["references"]
        )
    assert check_joint_review(path)["rubric_and_references"] == "approved"
    with pytest.raises(ValueError, match="Human decision missing"):
        check_joint_review(path, require_blind=True)
    decision["package_hash"] = "wrong"
    (path / "review-decision.json").write_text(json.dumps(decision))
    with pytest.raises(ValueError, match="another package"):
        check_joint_review(path)


def test_small_export_and_tampering_checks_use_temporary_review_stubs(
    package, tmp_path, monkeypatch
):
    import json
    from scripts.aml_dataset import mass_release

    reference = tmp_path / "review"
    write_package(package, reference)
    real_candidates = mass_release.candidates
    # Only this unit test replaces human gates and uses 24 cases. No approvals
    # or release files are written to project resources.
    monkeypatch.setattr(mass_release, "check_joint_review", lambda *a, **k: None)
    monkeypatch.setattr(mass_release, "verify_pilot_review", lambda *a, **k: None)
    monkeypatch.setattr(
        mass_release,
        "candidates",
        lambda refs, count, seed, sink=None: real_candidates(refs, 24, seed, sink),
    )
    destination = tmp_path / "test-export"
    report = mass_release.generate_mass(
        reference, destination, "release", pilot_dir=tmp_path / "stub-pilot"
    )
    assert report["count"] == 24 and report["shortfall"] == 19976
    assert mass_release.validate_mass(destination)["count"] == 24
    schema = json.loads((destination / "feature-schema.json").read_text())
    schema["columns"].append("baseline")
    (destination / "feature-schema.json").write_text(json.dumps(schema))
    with pytest.raises(ValueError, match="training parents"):
        mass_release.validate_mass(destination)


def test_reviewed_direction_inactivity_recurrence_volume_and_background():
    from scripts.check_expanded_balance import demo_config, demo_steps

    config = demo_config()
    config["behavior"]["history"]["operations"] = []
    steps = demo_steps(config)
    for step in steps:
        if step.get("sender_id"):
            step["sender_id"] = "C"
        if step.get("recipient_id"):
            step["recipient_id"] = "C"

    def score(values, cfg):
        return label(extract_features(values, cfg), rubric())[0]

    intense = score(steps, config)
    unknown = deepcopy(config)
    unknown["behavior"]["history"]["operations"] = None
    assert intense > score(steps, unknown)
    two_payments = [steps[i] for i in (0, 1, 3, 4)]
    assert score(two_payments, config) < 25 < intense
    smaller = deepcopy(steps)
    for step in smaller:
        if step["card"]["code"] in ("card_transfer", "cash_withdrawal"):
            step["amount"] = "10000.00"
    assert score(smaller, config) < intense
    background = demo_config()
    # Both histories have no C. Differences come from observed inactivity/background,
    # not changing the identity of an observed recipient.
    assert score(steps, background) < intense
    credits = [s for s in steps if s["card"]["code"] == "incoming_transfer"]
    assert score(credits, config) == 0


def test_salary_reduction_once_and_depends_on_income_basis(package):
    pair = next(p for p in package["pairs"] if p["kind"] == "salary")
    before = pair["before"]["target_risk_score"]
    assert pair["after"]["target_risk_score"] == pytest.approx(
        before * 0.75, abs=0.0001
    )
    features = deepcopy(pair["after"]["features"])
    features["income_basis"] = "no_reference"
    assert label(features, rubric())[0] == pytest.approx(before * .95, abs=.0001)
    features["count_salary"] = 2
    assert label(features, rubric())[0] == pytest.approx(before * .95, abs=.0001)
    features["count_salary"] = 0
    assert label(features, rubric())[0] == before
    features["count_salary"] = 1
    features["income_basis"] = "service_contract"
    assert label(features, rubric())[0] == pytest.approx(before * 0.8, abs=0.0001)
    features["income_basis"] = "payroll_registry"
    features["count_salary"] = 2
    assert label(features, rubric())[0] == pair["after"]["target_risk_score"]


def test_unknown_history_does_not_erase_context_or_invent_inactivity():
    from scripts.check_expanded_balance import demo_config, demo_steps

    config = demo_config()
    steps = demo_steps(config)
    for step in steps:
        if step.get("sender_id"):
            step["sender_id"] = "C"
        if step.get("recipient_id"):
            step["recipient_id"] = "C"
    unknown = deepcopy(config)
    unknown["behavior"]["history"]["operations"] = None
    unknown_features = extract_features(steps, unknown)
    unknown_score, explanation = label(unknown_features, rubric())
    assert unknown_features["history_empty"] == 0
    assert unknown_features["unobserved_recipient_share"] == 0
    uncertainty = next(t for t in explanation if "Неопределённость" in t["name"])
    assert uncertainty["contribution"] == 22
    assert (
        next(t for t in explanation if "после наблюдаемого" in t["name"])[
            "contribution"
        ]
        == 0
    )
    for history in (
        config["behavior"]["history"]["operations"],
        [config["behavior"]["history"]["operations"][1]],
        [config["behavior"]["history"]["operations"][2]],
    ):
        observed = deepcopy(config)
        observed["behavior"]["history"]["operations"] = history
        # The newly approved unknown-history half contribution may lower the total
        # by at most half of the capped ten-point flow component.
        assert unknown_score + 5 >= label(extract_features(steps, observed), rubric())[0]
    empty = deepcopy(config)
    empty["behavior"]["history"]["operations"] = []
    assert unknown_score < label(extract_features(steps, empty), rubric())[0]
    # Unknown history alone does not create a high score on a short diagnostic chain.
    assert label(extract_features(steps[:2], unknown), rubric())[0] < 25
    credits = [s for s in steps if s["card"]["code"] == "incoming_transfer"]
    assert label(extract_features(credits, unknown), rubric())[0] == 0


def test_multiple_purchases_give_small_bounded_effect_and_remain_observable(package):
    pair = next(p for p in package["pairs"] if p["kind"] == "purchase_background")
    assert pair["before"]["target_risk_score"] - pair["after"][
        "target_risk_score"
    ] == pytest.approx(0.9, abs=0.0001)
    assert (
        pair["after"]["totals"]["target_outflow"]
        == pair["before"]["totals"]["target_outflow"]
    )
    assert (
        pair["before"]["resources"]["energy"] - pair["after"]["resources"]["energy"]
        == 3
    )
    assert pair["before"]["resources"]["time"] - pair["after"]["resources"]["time"] == 3
    assert {r["features"]["count_purchase"] for r in package["references"]} == {
        0,
        1,
        2,
        3,
    }
    rules = rubric()
    no_bonus = deepcopy(rules)
    no_bonus.pop("purchase_background")
    for row in package["references"]:
        features = row["features"]
        delta = label(features, no_bonus)[0] - label(features, rules)[0]
        assert 0 <= delta <= 3.0001
        if features["count_purchase"] == 0:
            assert delta == 0
    # The cap does not become a per-card discount when both salary and purchases exist.
    features = deepcopy(pair["after"]["features"])
    features.update(
        count_salary=1, income_basis="payroll_registry", purchase_total=30000
    )
    assert label(features, no_bonus)[0] - label(features, rules)[0] == pytest.approx(
        3, abs=0.0001
    )
    features["target_outflow"] = 0
    assert label(features, rules)[0] >= 0
