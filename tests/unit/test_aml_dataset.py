import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

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


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def source(tmp_path):
    # The historical pilot also contains purposes retired from the editor.
    # Exercise the current export contract with an explicitly compatible case.
    rows = [json.loads(line) for line in
            (ROOT / "resources/aml_dataset/aml-v1/pilot/casebook.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    row = next(row for row in rows if row['scenario_id'] == 'P01-4-0')
    row.update(
        review_status="reviewed",
        review={
            "reviewer": "test-independent-reviewer",
            "method": "independent_domain_review",
            "date": "2026-09-16",
            "rationale": "Test fixture domain review; not production approval.",
        },
    )
    path = tmp_path / "source.jsonl"
    protocol = ROOT / "config/ml/aml-classifier-v1-protocol.json"

    def write(rows):
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )
        return path, protocol, tmp_path / "dataset"

    return row, write


def test_pilot_export_is_auditable_but_never_release_ready(source):
    from scripts.aml_dataset.aml_training import build_dataset, audit_dataset

    row, write = source
    paths = write([row])
    build_dataset(*paths)
    report = audit_dataset(paths[2])
    assert report["confirmed_rows"] == 1
    assert report["release_ready"] is False
    assert report["status"] == "not-release-ready"
    assert report["groups"] == 1
    assert "minimum_confirmed_rows" in report["unmet_gates"]
    with pytest.raises(FileExistsError):
        build_dataset(*paths)


def test_unreviewed_and_rejected_never_enter_supervised_csv(source):
    from scripts.aml_dataset.aml_training import build_dataset, audit_dataset

    row, write = source
    rejected = deepcopy(row)
    rejected.update(scenario_id="rejected", review_status="rejected")
    row.update(review_status="authored_unreviewed", review=None)
    paths = write([row, rejected])
    build_dataset(*paths)
    assert audit_dataset(paths[2])["confirmed_rows"] == 0
    with (paths[2] / "features.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == []


def test_relabelled_duplicate_stays_in_one_group_and_collision_is_reported(source):
    from scripts.aml_dataset.aml_training import build_dataset, audit_dataset

    row, write = source
    second = deepcopy(row)
    second.update(
        scenario_id="other-root", provenance_group_id="fake-independent", aml_label=1
    )
    second["author_truth"]["aml_episode_present"] = True
    second["public_snapshot"]["steps"][0]["step_id"] = (
        "00000000-0000-0000-0000-000000000001"
    )
    paths = write([row, second])
    build_dataset(*paths)
    report = audit_dataset(paths[2])
    assert report["groups"] == 1
    collisions = json.loads((paths[2] / "collisions.json").read_text(encoding="utf-8"))
    assert len(collisions["conflicting_labels"]) == 1


def test_audit_recomputes_features_even_if_attacker_updates_checksums(source):
    from scripts.aml_dataset.aml_training import build_dataset, audit_dataset

    row, write = source
    paths = write([row])
    build_dataset(*paths)
    directory = paths[2]
    features = directory / "features.csv"
    with features.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns, rows = reader.fieldnames, list(reader)
    rows[0][columns[1]] = "999999"
    with features.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifact_hashes"]["features.csv"] = hashlib.sha256(
        features.read_bytes()
    ).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="features.csv"):
        audit_dataset(directory)


def test_invalid_public_metadata_or_unachieved_objective_rejected(source):
    from scripts.aml_dataset.aml_training import build_dataset

    row, write = source
    row["public_snapshot"]["aml_label"] = 0
    with pytest.raises(ValueError, match="forbidden public"):
        build_dataset(*write([row]))
    row["public_snapshot"].pop("aml_label")
    row["public_snapshot"]["steps"] = row["public_snapshot"]["steps"][:1]
    with pytest.raises(ValueError, match="resource|objective"):
        build_dataset(*write([row]))


def test_provenance_links_actual_shared_history_even_with_new_ids(source):
    from scripts.aml_dataset.aml_provenance import connected_groups

    row, _ = source
    second = deepcopy(row)
    second.update(scenario_id="second", provenance_group_id="new-root")
    # Different observed route and feature vector; actual common history is the link.
    second["public_snapshot"]["steps"] = second["public_snapshot"]["steps"][:1]
    for event in second["public_snapshot"]["config"]["behavior"]["history"][
        "operations"
    ]:
        event["id"] = "renamed-" + event["id"]
    result = connected_groups(
        [row, second], {row["scenario_id"]: {"x": 1}, "second": {"x": 2}}
    )
    assert len(result["groups"]) == 1
    assert any(link["reason"] == "shared_nonempty_history" for link in result["links"])


def test_parents_link_transitively_and_empty_histories_do_not_create_dependence(source):
    from scripts.aml_dataset.aml_provenance import connected_groups

    row, _ = source
    rows = []
    for index in range(3):
        item = deepcopy(row)
        item.update(scenario_id=str(index), provenance_group_id=str(index))
        item["public_snapshot"]["config"]["behavior"]["history"]["operations"] = []
        item["public_snapshot"]["steps"] = item["public_snapshot"]["steps"][: index + 1]
        rows.append(item)
    features = {str(i): {"x": i} for i in range(3)}
    assert len(connected_groups(rows, features)["groups"]) == 3
    rows[1]["provenance"] = {"parent_ids": ["0"]}
    rows[2]["provenance"] = {"parent_ids": ["1"]}
    assert len(connected_groups(rows, features)["groups"]) == 1


def test_amount_mutation_and_party_rename_do_not_manufacture_a_new_origin(source):
    from scripts.aml_dataset.aml_provenance import connected_groups

    row, _ = source
    row["public_snapshot"]["config"]["behavior"]["history"]["operations"] = []
    second = deepcopy(row)
    second.update(scenario_id="renamed", provenance_group_id="pretend-new-origin")
    second["public_snapshot"]["steps"][0]["amount"] = "79999.99"

    def rename(value):
        if isinstance(value, dict):
            return {k: rename(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rename(v) for v in value]
        return "renamed-party" if value == "A" else value

    second["public_snapshot"] = rename(second["public_snapshot"])
    result = connected_groups(
        [row, second], {row["scenario_id"]: {"x": 1}, "renamed": {"x": 2}}
    )
    assert len(result["groups"]) == 1
    assert any(link["reason"] == "near_duplicate_shape" for link in result["links"])


def test_unresolved_diagnostic_preserves_confirmed_sibling_and_declares_dependence(
    source,
):
    from scripts.aml_dataset.aml_training import build_dataset, audit_dataset

    row, write = source
    unresolved = deepcopy(row)
    unresolved.update(
        scenario_id="unresolved", aml_label=None, label_status="unresolved"
    )
    unresolved["author_truth"]["aml_episode_present"] = None
    paths = write([row, unresolved])
    build_dataset(*paths)
    report = audit_dataset(paths[2])
    assert report["confirmed_rows"] == 1
    assert report["diagnostic_rows"] == {"unresolved": 1}
    diagnostic = json.loads(
        (paths[2] / "diagnostics/unresolved.jsonl").read_text(encoding="utf-8")
    )
    assert diagnostic["independent"] is False
    assert diagnostic["parent_split"] == "train"


def test_balanced_group_allocation_is_exact_for_1200_groups():
    from scripts.aml_dataset.aml_training import split_groups

    rows = {str(i): {"aml_label": i % 2} for i in range(1200)}
    groups = {str(i): [str(i)] for i in range(1200)}
    assignment = split_groups(groups, rows)
    counts = {
        split: sum(value == split for value in assignment.values())
        for split in set(assignment.values())
    }
    assert counts == {
        "train": 720,
        "validation": 180,
        "calibration-fit": 120,
        "calibration-check": 60,
        "test": 120,
    }
    for split in counts:
        labels = [
            rows[gid]["aml_label"]
            for gid, value in assignment.items()
            if value == split
        ]
        assert labels.count(0) == labels.count(1)
    assert assignment == split_groups(dict(reversed(list(groups.items()))), rows)


def test_shared_origin_split_tamper_is_detected_under_optimized_python(source):
    from scripts.aml_dataset.aml_training import build_dataset

    row, write = source
    other = deepcopy(row)
    other["scenario_id"] = "variant"
    paths = write([row, other])
    build_dataset(*paths)
    directory = paths[2]
    split = directory / "split.csv"
    with split.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns, records = reader.fieldnames, list(reader)
    records[1]["split"] = "test"
    with split.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifact_hashes"]["split.csv"] = hashlib.sha256(
        split.read_bytes()
    ).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-O",
            "-c",
            "import sys; from scripts.aml_dataset.aml_training import audit_dataset; audit_dataset(sys.argv[1])",
            str(directory),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "group/split" in result.stderr


def test_neutral_observation_hash_preserves_identity_links_under_renaming(source):
    from scripts.aml_dataset.aml_provenance import digest, neutral_observation

    row, _ = source
    public = row["public_snapshot"]
    original = digest(neutral_observation(public))
    replacements = {
        p["id"]: f"new-{i}"
        for i, p in enumerate(public["config"]["behavior"]["counterparties"])
    }
    replacements.update(
        {
            f["id"]: f"claim-{i}"
            for i, f in enumerate(public["config"]["behavior"]["aml_context"]["facts"])
        }
    )

    def rename(value, key=""):
        if isinstance(value, dict):
            return {k: rename(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [rename(v, key) for v in value]
        return (
            replacements.get(value, value)
            if isinstance(value, str)
            and key
            in {
                "id",
                "sender_id",
                "recipient_id",
                "counterparty_id",
                "counterparty_ids",
                "claim_id",
                "opening_balance_facts",
            }
            else value
        )

    renamed = rename(public)
    renamed["config"]["behavior"]["counterparties"].reverse()
    renamed["config"]["behavior"]["aml_context"]["facts"].reverse()
    assert digest(neutral_observation(renamed)) == original


def test_preregistered_challenge_reserves_entire_connected_component(source):
    from scripts.aml_dataset.aml_training import build_dataset, audit_dataset

    row, write = source
    other = deepcopy(row)
    other.update(scenario_id="heldout", challenge_set="family-held-out")
    paths = write([row, other])
    protocol = json.loads(paths[1].read_text(encoding="utf-8"))
    protocol["family_held_out"] = [row["family_id"]]
    registered = paths[0].parent / "registered-protocol.json"
    registered.write_text(json.dumps(protocol), encoding="utf-8")
    build_dataset(paths[0], registered, paths[2])
    report = audit_dataset(paths[2])
    assert report["confirmed_rows"] == 0
    assert report["challenge_rows"] == {"family-held-out": 2}


def test_coverage_reports_entirely_missing_supported_channels(source):
    from scripts.aml_dataset.aml_training import build_dataset

    row, write = source
    paths = write([row])
    build_dataset(*paths)
    coverage = json.loads((paths[2] / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["channel"]["crypto_p2p"] == {
        "class_0": 0,
        "class_1": 0,
        "both_classes": False,
    }
    assert any(c["cell"] == "crypto_p2p" for c in coverage["missing_cells"])


def test_audit_cli_cannot_mutate_immutable_dataset_with_report(source):
    from scripts.aml_dataset.aml_training import build_dataset

    row, write = source
    paths = write([row])
    build_dataset(*paths)
    output = paths[2] / "new-report.json"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "scripts.validate_aml_dataset",
         "--dataset", str(paths[2]), "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not output.exists()


def test_history_dependence_uses_instants_and_events_not_current_party_attributes(source):
    from datetime import datetime, timezone
    from scripts.aml_dataset.aml_provenance import connected_groups

    row, _ = source
    second = deepcopy(row)
    second.update(scenario_id="other-history", provenance_group_id="unrelated-id")
    second["public_snapshot"]["steps"] = second["public_snapshot"]["steps"][:1]
    behavior = second["public_snapshot"]["config"]["behavior"]
    for event in behavior["history"]["operations"]:
        event["occurred_at"] = datetime.fromisoformat(event["occurred_at"]).astimezone(timezone.utc).isoformat()
    behavior["counterparties"][0]["information_status"] = "unknown"
    result = connected_groups([row, second], {row["scenario_id"]: {"x": 1}, "other-history": {"x": 2}})
    assert len(result["groups"]) == 1
    assert any(link["reason"] == "shared_nonempty_history" for link in result["links"])


@pytest.mark.parametrize("mutation", ["objective", "balance", "fee", "operation_cost", "card_limit"])
def test_dataset_refuses_financial_drift_even_if_modified_engine_can_submit(source, mutation):
    from scripts.aml_dataset.aml_training import build_dataset
    row, write = source
    config = row["public_snapshot"]["config"]
    if mutation == "objective":
        config["objectives"].update(target_outflow="78000.00", max_actions=1)
        row["public_snapshot"]["steps"] = [next(s for s in row["public_snapshot"]["steps"] if s["card"]["code"] == "card_transfer")]
        row["public_snapshot"]["steps"][0]["interval_minutes"] = None
    elif mutation == "balance":
        config["resources"]["initial_balance"] = "190000.00"
    elif mutation == "fee":
        next(c for c in config["card_snapshots"] if c["code"] == "card_transfer")["fee_rate"] = "0.000000"
    elif mutation == "operation_cost":
        next(c for c in config["operations"] if c["code"] == "card_transfer")["energy_cost"] = 0
    else:
        next(c for c in config["card_snapshots"] if c["code"] == "card_transfer")["max_amount"] = "100000.00"
    with pytest.raises(ValueError, match="financial contract"):
        build_dataset(*write([row]))


def test_row_tag_cannot_create_an_unregistered_family_holdout(source):
    from scripts.aml_dataset.aml_training import build_dataset
    row, write = source
    row["challenge_set"] = "family-held-out"
    with pytest.raises(ValueError, match="preregistered"):
        build_dataset(*write([row]))
