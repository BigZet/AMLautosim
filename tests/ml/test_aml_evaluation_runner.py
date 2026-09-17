"""Runner tests use real tiny CatBoost models; never production acceptance evidence."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from catboost import CatBoostClassifier, Pool

from scripts.aml_dataset.aml_casebook import build_casebook
from scripts.package_aml_classifier import create_candidate_package
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    extract_features,
)


@pytest.fixture
def tiny_candidate(tmp_path):
    from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes

    # Use existing compatible cases; retired purposes remain rejected by runtime.
    rows = [
        r for r in build_casebook()
        if r["aml_label"] is not None
        and all(s["purpose_code"] in allowed_purposes(s) for s in r["public_snapshot"]["steps"])
    ][:8]
    frame = pd.DataFrame([extract_features(**r["public_snapshot"]) for r in rows])
    model = CatBoostClassifier(
        iterations=8,
        depth=4,
        random_seed=2026091601,
        verbose=False,
        thread_count=1,
        allow_writing_files=False,
    )
    model.fit(
        Pool(
            frame,
            label=[r["aml_label"] for r in rows],
            cat_features=CATEGORICAL_FEATURES,
        )
    )
    native = tmp_path / "tiny.cbm"
    model.save_model(str(native))
    schema = {
        "version": FEATURE_VERSION,
        "features": list(FEATURE_NAMES),
        "types": {
            n: "categorical" if n in CATEGORICAL_FEATURES else "numeric"
            for n in FEATURE_NAMES
        },
    }
    package = tmp_path / "candidate"
    create_candidate_package(
        model=native,
        calibrator={"method": "none"},
        schema=schema,
        protocol={
            "version": "aml-labels-v1",
            "population_id": "aml-game-balanced-v1",
            "confirmed_class_prior": 0.5,
        },
        dictionary=json.loads(
            Path("config/model/aml-classifier-v1-feature-descriptions.json").read_text(
                encoding="utf-8"
            )
        ),
        allowed_profiles=sorted(
            {r["public_snapshot"]["config"]["behavior"]["profile"]["id"] for r in rows}
        ),
        category_allowlist={n: sorted(set(frame[n])) for n in CATEGORICAL_FEATURES},
        output=package,
    )
    for i, row in enumerate(rows):
        row["group_id"] = f"origin-{i // 2}"
    return package, rows, frame, schema


def test_evaluate_rejects_non_test_before_opening_paths(tmp_path):
    from scripts import evaluate_aml_classifier as runner

    assert callable(getattr(runner, "evaluate", None)), "Missing evaluation entry point"
    with pytest.raises(ValueError, match="test"):
        runner.evaluate(tmp_path / "missing", tmp_path / "missing", "validation")


def test_training_upstream_roster_requires_demo_binding_source():
    from hashlib import sha256
    from scripts import evaluate_aml_classifier as runner

    names = {
        "scripts/aml_classifier.py",
        "scripts/train_aml_classifier.py",
        "scripts/training_environment.py",
        "scripts/aml_demo_training.py",
    }
    hashes = {name: sha256(Path(name).read_bytes()).hexdigest() for name in names}
    runner.verify_upstream_sources("training", hashes)
    del hashes["scripts/aml_demo_training.py"]
    with pytest.raises(ValueError, match="source roster"):
        runner.verify_upstream_sources("training", hashes)


def test_unbound_raw_candidate_cannot_open_test(tiny_candidate, tmp_path):
    from scripts import evaluate_aml_classifier as runner

    assert callable(getattr(runner, "evaluate", None)), "Missing evaluation entry point"
    with pytest.raises(ValueError, match="bound|provenance"):
        runner.evaluate(tmp_path / "missing-dataset", tiny_candidate[0], "test")
    assert not (tmp_path / ".aml-test-access").exists()


def test_real_predictions_diagnostics_and_unresolved_preserve_labels(
    tiny_candidate, tmp_path
):
    from scripts import evaluate_aml_classifier as runner

    assert callable(getattr(runner, "score_rows", None)), "Missing real scoring helper"
    from src.aml_workshop_simulator.services.aml_probability_model import (
        AMLProbabilityModel,
    )

    model = AMLProbabilityModel(tiny_candidate[0], offline_candidate=True)
    rows = tiny_candidate[1]
    predictions = runner.score_rows(model, rows)
    assert [p["scenario_id"] for p in predictions] == [r["scenario_id"] for r in rows]
    assert [p["aml_label"] for p in predictions] == [r["aml_label"] for r in rows]
    expected = model.classifier.predict_proba(
        Pool(tiny_candidate[2], cat_features=CATEGORICAL_FEATURES)
    )[:, 1]
    assert np.allclose([p["probability"] for p in predictions], expected)
    report = runner.prediction_report(predictions)
    assert report["status"] == "complete" and report["rows"] == 8
    assert sum(sum(row) for row in report["diagnostics"]["confusion_matrix"]) == 8
    unknown = [{**p, "aml_label": None} for p in predictions]
    diagnostic = runner.prediction_report(unknown)
    assert diagnostic["metrics"] is None and diagnostic["confirmed_rows"] == 0
    assert "grey_gate" not in diagnostic
    runner.write_evaluation_artifacts(
        {"predictions": predictions}, tmp_path / "report.json"
    )
    assert {p.name for p in (tmp_path / "report.artifacts").glob("*.svg")} == {
        "confusion.svg",
        "roc.svg",
        "pr.svg",
        "reliability.svg",
        "class-histogram.svg",
    }
    with pytest.raises(FileExistsError):
        runner.write_evaluation_artifacts(
            {"predictions": predictions}, tmp_path / "report.json"
        )


def test_test_identity_ignores_manifest_source_reexports_but_binds_observations(
    tmp_path,
):
    from scripts import evaluate_aml_classifier as runner

    assert callable(getattr(runner, "frozen_test_identity", None)), (
        "Missing stable frozen-test identity"
    )
    (tmp_path / "split.csv").write_text(
        "scenario_id,group_id,split,aml_label\na,g,train,0\nb,h,test,1\n",
        encoding="utf-8",
    )
    (tmp_path / "features.csv").write_text(
        "scenario_id,x\na,1\nb,2\n", encoding="utf-8"
    )
    (tmp_path / "feature-schema.json").write_text(
        json.dumps({"features": ["x"], "types": {"x": "numeric"}}), encoding="utf-8"
    )
    identity = runner.frozen_test_identity(tmp_path)
    (tmp_path / "manifest.json").write_text(
        '{"source_hashes":{"a":"changed"}}', encoding="utf-8"
    )
    (tmp_path / "features.csv").write_text(
        "scenario_id,x\na,999\nb,2\n", encoding="utf-8"
    )
    assert runner.frozen_test_identity(tmp_path) == identity
    (tmp_path / "features.csv").write_text(
        "scenario_id,x\na,999\nb,3\n", encoding="utf-8"
    )
    assert runner.frozen_test_identity(tmp_path) != identity


def test_test_receipt_survives_cosmetic_group_names_and_numeric_format(tmp_path):
    from scripts import evaluate_aml_classifier as runner

    (tmp_path / "feature-schema.json").write_text(
        json.dumps(
            {
                "features": ["x", "kind"],
                "types": {"x": "numeric", "kind": "categorical"},
            }
        ),
        encoding="utf-8",
    )
    split = tmp_path / "split.csv"
    features = tmp_path / "features.csv"
    split.write_text(
        "scenario_id,group_id,split,aml_label\na,old,test,0\nb,old,test,1\n",
        encoding="utf-8",
    )
    features.write_text("scenario_id,x,kind\na,1.0,01\nb,-0.0,01\n", encoding="utf-8")
    identity = runner.frozen_test_identity(tmp_path)
    runner.claim_test_access(identity, "first-candidate", tmp_path / "receipts")
    split.write_text(
        "scenario_id,group_id,split,aml_label\nb,renamed,test,1\na,renamed,test,0\n",
        encoding="utf-8",
    )
    features.write_text(
        "scenario_id,x,kind\nb,0.000,01\na,1.000,01\n", encoding="utf-8"
    )
    assert runner.frozen_test_identity(tmp_path) == identity
    with pytest.raises(ValueError):
        runner.claim_test_access(
            runner.frozen_test_identity(tmp_path),
            "second-candidate",
            tmp_path / "receipts",
        )
    features.write_text("scenario_id,x,kind\nb,0.000,1\na,1.000,01\n", encoding="utf-8")
    assert runner.frozen_test_identity(tmp_path) != identity
    features.write_text(
        "scenario_id,x,kind\nb,0.000,01\na,1.000,01\n", encoding="utf-8"
    )
    split.write_text(
        "scenario_id,group_id,split,aml_label\nb,newgroup,test,1\na,renamed,test,0\n",
        encoding="utf-8",
    )
    assert runner.frozen_test_identity(tmp_path) != identity


def test_diagnostic_reliability_marks_group_support_in_table_and_plot(tmp_path):
    from scripts.aml_evaluation_artifacts import (
        prediction_report,
        write_evaluation_artifacts,
    )

    predictions = [
        dict(
            scenario_id=str(i),
            group_id="same-origin",
            aml_label=i % 2,
            probability=0.02 + i / 1000,
        )
        for i in range(8)
    ]
    table = prediction_report(predictions)["diagnostics"]["reliability"]
    assert table[0]["rows"] == 8
    assert table[0]["groups"] == 1
    assert table[0]["support"] == "insufficient-support"
    write_evaluation_artifacts(
        {"predictions": predictions, "release_ready": False}, tmp_path / "report.json"
    )
    chart = (tmp_path / "report.artifacts/reliability.svg").read_text(encoding="utf-8")
    assert "Insufficient support" in chart
    assert "1 groups" in chart


def test_tiny_runner_orchestration_keeps_all_rows_and_failed_release_gates(
    tiny_candidate, tmp_path, monkeypatch
):
    """Isolate reviewed-provenance boundaries; all scoring/fitting/metrics stay real.

    This fixture is explicitly NOT a release-ready dataset. Auditing and calibration
    acceptance are tested separately; their expensive production evidence is not forged.
    """
    import csv
    from copy import deepcopy
    from scripts import evaluate_aml_classifier as runner
    from scripts.aml_dataset.aml_training import json_bytes, jsonl_bytes
    from scripts.aml_ablations import fit_ablations as real_fit

    package, rows, frame, schema = tiny_candidate
    dataset = tmp_path / "fixture-dataset"
    dataset.mkdir()
    train_rows, test_rows = deepcopy(rows), deepcopy(rows)
    for split, selected in [("train", train_rows), ("test", test_rows)]:
        for i, row in enumerate(selected):
            row.update(
                scenario_id=f"{split}-{i}", group_id=f"{split}-g{i // 2}", split=split
            )
    (dataset / "feature-schema.json").write_bytes(json_bytes(schema))
    (dataset / "scenarios.jsonl").write_bytes(jsonl_bytes(train_rows + test_rows))
    with (dataset / "split.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["scenario_id", "group_id", "split", "aml_label"]
        )
        writer.writeheader()
        writer.writerows(
            {k: row[k] for k in writer.fieldnames} for row in train_rows + test_rows
        )
    feature_rows = pd.concat([frame, frame], ignore_index=True)
    feature_rows.insert(
        0, "scenario_id", [r["scenario_id"] for r in train_rows + test_rows]
    )
    feature_rows.to_csv(dataset / "features.csv", index=False)
    for filename in ("coverage.json", "collisions.json"):
        (dataset / filename).write_bytes(json_bytes({"scope": "tiny fixture only"}))
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["dataset_manifest_sha256"] = "fixture-only-not-reviewed"
    for filename, value in {
        "test-ids.json": [r["scenario_id"] for r in test_rows],
        "training-selection.json": {"depth": 4, "l2_leaf_reg": 3, "trees": 8},
        "training-baselines.json": {
            "constant_prior": {
                "prior": float(np.mean([r["aml_label"] for r in train_rows]))
            }
        },
    }.items():
        (package / filename).write_bytes(json_bytes(value))
        manifest["artifact_hashes"][filename] = runner._file_hash(package / filename)
    (package / "manifest.json").write_bytes(json_bytes(manifest))
    calls = []
    monkeypatch.setattr(
        runner,
        "_verify_candidate",
        lambda *args: {"scope": "isolated fixture provenance boundary"},
    )
    monkeypatch.setattr(
        runner,
        "_reproduce_calibration",
        lambda *args: {"scope": "isolated fixture calibration boundary"},
    )

    def fit(training, actual_schema, selection):
        assert training["ids"] == [r["scenario_id"] for r in train_rows]
        result = real_fit(training, actual_schema, selection)
        calls.append("ablations-fitted")
        return result

    def claim(dataset_identity, candidate_identity, directory):
        assert calls == ["ablations-fitted"]
        calls.append("test-claimed")
        return runner_original_claim(
            dataset_identity, candidate_identity, tmp_path / "receipts"
        )

    runner_original_claim = runner.claim_test_access
    import scripts.aml_ablations

    monkeypatch.setattr(scripts.aml_ablations, "fit_ablations", fit)
    monkeypatch.setattr(runner, "claim_test_access", claim)
    report = runner.evaluate(dataset, package, "test")
    assert calls == ["ablations-fitted", "test-claimed"]
    assert report["test_ids"] == [r["scenario_id"] for r in test_rows]
    assert report["main_test"]["rows"] == len(test_rows)
    assert report["main_test"]["bootstrap"]["repeats"] == 2000
    assert report["release_ready"] is False
    assert report["gates"]["main_test"] is False
    assert report["gates"]["subgroups"] is False
    assert report["gates"]["challenge_reports"] is False
    assert report["gates"]["ablation_reports"] is True
    assert set(report["gates"]) == {
        "dataset_provenance",
        "main_test",
        "subgroups",
        "challenge_reports",
        "ablation_reports",
    }
    assert all(r["status"] == "missing" for r in report["challenge_reports"].values())
    assert all(
        r["status"] == "complete" and r["rows"] == 8
        for r in report["ablation_reports"].values()
    )
    assert "Assumption-only" in report["prior_sensitivity"]["scope"]


def test_calibration_reproduction_rejects_fabricated_support(
    tiny_candidate, tmp_path, monkeypatch
):
    from scripts import evaluate_aml_classifier as runner
    from scripts import aml_classifier
    from scripts.calibrate_aml_classifier import select_calibrator
    from scripts.aml_dataset.aml_provenance import digest
    from src.aml_workshop_simulator.services.aml_probability_model import (
        AMLProbabilityModel,
    )

    package, rows, frame, schema = tiny_candidate
    model = AMLProbabilityModel(package, offline_candidate=True)
    labels = np.array([r["aml_label"] for r in rows])
    fit_groups = [f"fit-{i}" for i in range(len(rows))]
    check_groups = [f"check-{i}" for i in range(len(rows))]
    observations = [digest(r) for r in frame.to_dict(orient="records")]
    margins = model.classifier.predict(
        Pool(frame, cat_features=CATEGORICAL_FEATURES), prediction_type="RawFormulaVal"
    )
    artifact, selection = select_calibrator(
        margins,
        labels,
        margins,
        labels,
        fit_groups=fit_groups,
        check_groups=check_groups,
        fit_observation_hashes=observations,
    )
    # Candidate claims support that these real, tiny disjoint groups cannot establish.
    model.calibrator = artifact
    claimed = {
        **selection,
        "support_gate_passed": True,
        "low_groups": 20,
        "high_groups": 20,
    }
    (package / "calibration-selection.json").write_text(
        json.dumps(claimed), encoding="utf-8"
    )
    monkeypatch.setattr(
        aml_classifier,
        "load_splits",
        lambda dataset, splits: (
            schema,
            {
                "calibration-fit": {
                    "features": frame,
                    "labels": labels,
                    "groups": fit_groups,
                },
                "calibration-check": {
                    "features": frame,
                    "labels": labels,
                    "groups": check_groups,
                },
            },
        ),
    )
    with pytest.raises(ValueError, match="calibration cannot be reproduced"):
        runner._reproduce_calibration(tmp_path, package, model)


def test_cli_refuses_existing_output_before_touching_dataset(tmp_path):
    import os
    import subprocess
    import sys

    output = tmp_path / "result.json"
    output.write_text("preserve-existing", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-O",
            "-m",
            "scripts.evaluate_aml_classifier",
            "--dataset",
            str(tmp_path / "missing-dataset"),
            "--package",
            str(tmp_path / "missing-package"),
            "--split",
            "test",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    assert completed.returncode != 0
    assert "Refusing existing evaluation output" in completed.stderr
    assert output.read_text(encoding="utf-8") == "preserve-existing"


def test_challenges_score_real_rows_and_keep_missing_or_unsupported_failed(
    tiny_candidate, tmp_path
):
    from copy import deepcopy
    from scripts import evaluate_aml_classifier as runner
    from scripts.aml_dataset.aml_training import jsonl_bytes
    from src.aml_workshop_simulator.services.aml_probability_model import (
        AMLProbabilityModel,
    )

    assert callable(getattr(runner, "evaluate_challenges", None)), (
        "Missing challenge evaluation boundary"
    )
    model = AMLProbabilityModel(tiny_candidate[0], offline_candidate=True)
    rows = deepcopy(tiny_candidate[1])
    for row in rows:
        row["aml_label"] = None
    diagnostics = tmp_path / "diagnostics"
    diagnostics.mkdir()
    (diagnostics / "unresolved.jsonl").write_bytes(jsonl_bytes(rows))
    result = runner.evaluate_challenges(tmp_path, model)
    assert result["unresolved"]["status"] == "complete"
    assert result["unresolved"]["rows"] == len(rows)
    assert result["unresolved"]["metrics"] is None
    assert result["unresolved"]["independent"] is False
    assert all(
        result[name]["status"] == "missing"
        for name in ("masked-context", "new-combinations", "family-held-out")
    )
    unsupported = deepcopy(tiny_candidate[1])
    unsupported[0]["public_snapshot"]["config"]["behavior"]["profile"]["id"] = (
        "unseen-profile"
    )
    (diagnostics / "masked-context.jsonl").write_bytes(jsonl_bytes(unsupported))
    result = runner.evaluate_challenges(tmp_path, model)
    assert result["masked-context"]["status"] == "failed"
    assert result["masked-context"]["rows"] == len(unsupported)
    assert result["masked-context"]["predictions_sha256"] is None
    assert result["unresolved"]["status"] == "complete"


def test_upstream_source_binding_requires_exact_protocol_sources():
    from scripts import evaluate_aml_classifier as runner

    assert callable(getattr(runner, "verify_upstream_sources", None)), (
        "Missing exact upstream source validation"
    )
    root = Path(runner.__file__).resolve().parents[1]
    expected = {
        "scripts/calibrate_aml_classifier.py",
        "src/aml_workshop_simulator/services/aml_calibration.py",
    }
    hashes = {name: runner._file_hash(root / name) for name in expected}
    runner.verify_upstream_sources("calibration", hashes)
    for invalid in (
        {},
        {
            "scripts/calibrate_aml_classifier.py": hashes[
                "scripts/calibrate_aml_classifier.py"
            ]
        },
        {
            **hashes,
            "scripts/evaluate_aml_classifier.py": runner._file_hash(
                Path(runner.__file__)
            ),
        },
        {name: "0" * 64 for name in expected},
    ):
        with pytest.raises(ValueError, match="source"):
            runner.verify_upstream_sources("calibration", invalid)
