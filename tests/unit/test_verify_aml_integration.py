"""Verifier gates use an explicit inference/provenance boundary, not a release claim."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def fixture_inputs(count=100):
    saved = json.loads(
        Path("tests/fixtures/scoring-api/result-v4.json").read_text(encoding="utf-8")
    )["explanation"]
    saved.update(
        aml_probability=0.5,
        uncalibrated_probability=0.5,
        raw_margin=0.0,
        risk_score=50.0,
        category="review",
        base_margin=0.0,
        shap_residual=0.0,
        shap_values=[
            dict(
                feature="test-feature",
                value=0,
                contribution=0.0,
                title="Test",
                description="Test boundary",
            )
        ],
        calibration=dict(
            parameters={"method": "none"},
            input_space="raw_margin",
            output_space="probability",
        ),
    )
    rows = [
        dict(
            scenario_id=str(i),
            group_id=f"g{i // 2}",
            aml_label=i % 2,
            split="test",
            public_snapshot=dict(steps=[], config={"behavior": {}}),
        )
        for i in range(count)
    ]
    reference = dict(
        test_ids=[r["scenario_id"] for r in rows],
        predictions=[
            dict(
                scenario_id=r["scenario_id"],
                group_id=r["group_id"],
                aml_label=r["aml_label"],
                probability=0.5,
                raw_margin=0.0,
            )
            for r in rows
        ],
    )
    from src.aml_workshop_simulator.services.aml_probability_model import canonical_hash

    saved["context_sha256"] = canonical_hash({})
    model = SimpleNamespace(
        model_identity=deepcopy(saved["model_identity"]),
        manifest={"dataset_manifest_sha256": "a" * 64},
        schema={"features": ["test-feature"]},
        calibrator={"method": "none"},
        classifier=SimpleNamespace(classes_=[0, 1]),
        predict=lambda **kw: deepcopy(saved),
    )
    return model, rows, reference, saved


def test_verifier_checks_full_manifest_roster_and_reports_scoped_success(
    tmp_path, monkeypatch
):
    from scripts import verify_aml_integration as verifier

    model, rows, reference, _ = fixture_inputs()
    calls = []
    original = model.predict

    def predict(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    model.predict = predict
    monkeypatch.setattr(
        verifier, "load_verified_inputs", lambda *args: (model, rows, reference)
    )
    output = tmp_path / "report.json"
    report = verifier.verify(tmp_path / "dataset", tmp_path / "package", output)
    assert report["passed"] is True
    assert report["scope"] == "offline-runtime-test-and-serial-performance-only"
    assert report["test_ids"] == reference["test_ids"]
    assert len(calls) == 100
    assert report["max_probability_error"] == 0
    assert report["max_shap_residual"] == 0
    assert json.loads(output.read_text(encoding="utf-8")) == report
    with pytest.raises(FileExistsError):
        verifier.verify(tmp_path / "dataset", tmp_path / "package", output)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "probability",
        "shap",
        "context",
        "identity",
        "class_mapping",
        "short",
        "slow",
        "category",
        "risk_score",
        "raw_probability",
        "calibration",
        "shap_roster",
        "mutated_input",
        "nonfinite_offline",
    ],
)
def test_verifier_never_writes_success_for_failed_gate(tmp_path, monkeypatch, defect):
    from scripts import verify_aml_integration as verifier

    model, rows, reference, saved = fixture_inputs(99 if defect == "short" else 100)
    if defect == "missing":
        reference["predictions"].pop()
    elif defect == "duplicate":
        reference["predictions"][-1] = deepcopy(reference["predictions"][0])
    elif defect == "probability":
        saved.update(aml_probability=0.6, risk_score=60.0)
    elif defect == "shap":
        saved["base_margin"] = 1.0
    elif defect == "context":
        saved["context_sha256"] = "0" * 64
    elif defect == "identity":
        saved["model_identity"]["model_sha256"] = "0" * 64
    elif defect == "class_mapping":
        model.classifier.classes_ = [1, 0]
    elif defect == "category":
        saved["category"] = "low"
    elif defect == "risk_score":
        saved["risk_score"] = 49.0
    elif defect == "raw_probability":
        saved["uncalibrated_probability"] = 0.4
    elif defect == "calibration":
        saved["calibration"]["parameters"] = {"method": "sigmoid", "a": 1, "b": 0}
    elif defect == "shap_roster":
        saved["shap_values"][0]["feature"] = "wrong-feature"
    elif defect == "mutated_input":

        def mutate(**kwargs):
            kwargs["steps"].append({"injected": True})
            return deepcopy(saved)

        model.predict = mutate
    elif defect == "nonfinite_offline":
        reference["predictions"][0]["probability"] = float("nan")
    elif defect == "slow":
        import itertools

        monkeypatch.setattr(
            verifier.time,
            "perf_counter",
            lambda counter=itertools.count(): float(next(counter)),
        )
    monkeypatch.setattr(
        verifier, "load_verified_inputs", lambda *args: (model, rows, reference)
    )
    output = tmp_path / "report.json"
    with pytest.raises(ValueError):
        verifier.verify(tmp_path / "dataset", tmp_path / "package", output)
    assert not output.exists()


@pytest.mark.parametrize("destination", ["dataset", "package"])
def test_verifier_does_not_write_into_immutable_inputs(tmp_path, destination):
    from scripts import verify_aml_integration as verifier

    with pytest.raises(ValueError, match="outside immutable"):
        verifier.verify(
            tmp_path / "dataset",
            tmp_path / "package",
            tmp_path / destination / "report.json",
        )


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "audit",
        "dataset",
        "release",
        "split",
        "roster",
        "model",
        "calibration",
        "evaluation_dataset",
    ],
)
def test_loader_binds_audited_dataset_and_accepted_test(tmp_path, monkeypatch, defect):
    from scripts import verify_aml_integration as verifier

    dataset, package = tmp_path / "dataset", tmp_path / "package"
    dataset.mkdir()
    package.mkdir()
    (dataset / "manifest.json").write_text("{}", encoding="utf-8")
    (dataset / "scenarios.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"scenario_id": "train-row", "split": "train"},
                {"scenario_id": "test-row", "split": "test"},
            ]
        ),
        encoding="utf-8",
    )
    dataset_hash = verifier.sha(dataset / "manifest.json")
    model = SimpleNamespace(
        manifest={"dataset_manifest_sha256": dataset_hash},
        model_identity={"model_sha256": "a" * 64, "calibration_sha256": "b" * 64},
    )
    reference = dict(
        release_ready=True,
        evaluated_split="test",
        test_ids=["test-row"],
        dataset_manifest_sha256=dataset_hash,
        **model.model_identity,
    )
    audit = {"release_ready": True, "unmet_gates": []}
    if defect == "audit":
        audit["unmet_gates"] = ["missing-independent-groups"]
    elif defect == "dataset":
        model.manifest["dataset_manifest_sha256"] = "0" * 64
    elif defect == "release":
        reference["release_ready"] = False
    elif defect == "split":
        reference["evaluated_split"] = "validation"
    elif defect == "roster":
        reference["test_ids"] = ["other-row"]
    elif defect in ("model", "calibration"):
        reference[defect + "_sha256"] = "0" * 64
    elif defect == "evaluation_dataset":
        reference["dataset_manifest_sha256"] = "0" * 64
    (package / "evaluation.json").write_text(json.dumps(reference), encoding="utf-8")
    (package / "test-ids.json").write_text('["test-row"]', encoding="utf-8")
    # Unit boundary only: no forged fixture is accepted by the production model.
    # A keyword-free constructor ensures the verifier cannot opt into candidates.
    monkeypatch.setattr(verifier, "AMLProbabilityModel", lambda path: model)
    monkeypatch.setattr(verifier, "audit_dataset", lambda path: audit)
    if defect is not None:
        with pytest.raises(ValueError):
            verifier.load_verified_inputs(dataset, package)
    else:
        loaded, rows, report = verifier.load_verified_inputs(dataset, package)
        assert loaded is model
        assert rows == [{"scenario_id": "test-row", "split": "test"}]
        assert report == reference
