"""Real CatBoost runtime and immutable package boundary checks."""

import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from catboost import CatBoostClassifier, Pool

from scripts.aml_dataset.aml_casebook import build_casebook
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    extract_features,
)

ROOT = Path(__file__).resolve().parents[2]


def runtime():
    name = "src.aml_workshop_simulator.services.aml_probability_model"
    assert importlib.util.find_spec(name) is not None, "probability runtime missing"
    return __import__(name, fromlist=["AMLProbabilityModel"])


@pytest.fixture(scope="module")
def observations():
    from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes

    # Use existing compatible cases; retired purposes remain rejected by runtime.
    rows = [
        r for r in build_casebook()
        if r["aml_label"] is not None
        and all(s["purpose_code"] in allowed_purposes(s) for s in r["public_snapshot"]["steps"])
    ][:8]
    return [r["public_snapshot"] for r in rows]


@pytest.fixture
def candidate(tmp_path, observations):
    runtime()
    from scripts.package_aml_classifier import create_candidate_package

    features = [extract_features(p["steps"], p["config"]) for p in observations]
    pool = Pool(
        [[f[n] for n in FEATURE_NAMES] for f in features],
        label=[0, 1] * 4,
        feature_names=FEATURE_NAMES,
        cat_features=[FEATURE_NAMES.index(n) for n in CATEGORICAL_FEATURES],
    )
    model = CatBoostClassifier(
        iterations=8,
        depth=2,
        random_seed=19,
        thread_count=1,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(pool)
    model.save_model(str(tmp_path / "tiny.cbm"))
    schema = dict(
        version=FEATURE_VERSION,
        features=FEATURE_NAMES,
        types={
            n: "categorical" if n in CATEGORICAL_FEATURES else "numeric"
            for n in FEATURE_NAMES
        },
    )
    create_candidate_package(
        model=tmp_path / "tiny.cbm",
        calibrator={"method": "sigmoid", "a": 1.2, "b": -0.1},
        schema=schema,
        protocol={
            "version": "aml-labels-v1",
            "population_id": "aml-game-balanced-v1",
            "confirmed_class_prior": 0.5,
        },
        dictionary=json.loads(
            (
                ROOT / "config/model/aml-classifier-v1-feature-descriptions.json"
            ).read_text(encoding="utf-8")
        ),
        allowed_profiles=[observations[0]["config"]["behavior"]["profile"]["id"]],
        category_allowlist={
            "income_basis": sorted({f["income_basis"] for f in features})
        },
        output=tmp_path / "candidate",
    )
    return tmp_path / "candidate", model, pool


def test_candidate_default_rejected_real_shap_and_reload_stable(
    candidate, observations
):
    package, original, pool = candidate
    cls = runtime().AMLProbabilityModel
    with pytest.raises(ValueError, match="release"):
        cls(package)
    first = cls(package, offline_candidate=True).predict(**observations[0])
    second = cls(package, offline_candidate=True).predict(**observations[0])
    assert first["schema_version"] == 4
    assert first["explanation_space"] == "raw_margin"
    assert first["shap_residual"] <= 1e-6
    assert first["uncalibrated_probability"] == pytest.approx(
        original.predict_proba(pool)[0, 1], abs=1e-8
    )
    assert first["aml_probability"] == pytest.approx(
        second["aml_probability"], abs=1e-8
    )
    assert first["risk_score"] == 100 * first["aml_probability"]
    assert first["base_margin"] + sum(
        f["contribution"] for f in first["shap_values"]
    ) == pytest.approx(first["raw_margin"], abs=1e-6)
    assert [f["feature"] for f in first["shap_values"]] == FEATURE_NAMES
    assert np.isfinite(first["aml_probability"])


@pytest.mark.parametrize(
    "damage",
    [
        "calibration.json",
        "model.cbm",
        "feature-schema.json",
        "dictionary.json",
        "protocol.json",
        "thresholds.json",
        "evaluation.json",
    ],
)
def test_corrupted_required_artifact_is_rejected(candidate, damage):
    package, _, _ = candidate
    (package / damage).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        runtime().AMLProbabilityModel(package, offline_candidate=True)


def test_context_is_separate_and_financial_or_profile_drift_is_rejected(
    candidate, observations
):
    package, _, _ = candidate
    model = runtime().AMLProbabilityModel(package, offline_candidate=True)
    public = deepcopy(observations[0])
    first = model.predict(**public)
    public["config"]["behavior"]["aml_context"]["facts"][0]["verification_status"] = (
        "unverified"
    )
    second = model.predict(**public)
    assert first["context_sha256"] != second["context_sha256"]
    assert first["model_identity"] == second["model_identity"]
    public["config"]["resources"]["initial_balance"] = "180001.00"
    with pytest.raises(ValueError, match="financial"):
        model.predict(**public)
    public = deepcopy(observations[0])
    public["config"]["behavior"]["profile"]["id"] = "unsupported"
    with pytest.raises(ValueError, match="profile"):
        model.predict(**public)


def test_shared_financial_contract_matches_dataset_policy(observations):
    runtime()
    from src.aml_workshop_simulator.services.aml_contract import (
        financial_projection,
        fixed_financial_contract,
    )
    from scripts.aml_dataset.aml_training import (
        financial_projection as dataset_projection,
    )

    assert financial_projection(observations[0]["config"]) == dataset_projection(
        observations[0]["config"]
    )
    assert financial_projection(observations[0]["config"]) == fixed_financial_contract()


def test_production_packager_refuses_absent_release_evidence(tmp_path):
    runtime()
    from scripts.package_aml_classifier import package_classifier

    with pytest.raises((ValueError, FileNotFoundError)):
        package_classifier(
            training=tmp_path / "training",
            calibration=tmp_path / "calibration",
            dataset=tmp_path / "dataset",
            dictionary=ROOT
            / "config/model/aml-classifier-v1-feature-descriptions.json",
            allowed_profiles=["x"],
            category_allowlist={"income_basis": ["unknown"]},
            output=tmp_path / "release",
        )
    assert not (tmp_path / "release").exists()


def test_runtime_rejects_channels_outside_evaluated_allowlist(candidate, observations):
    package, _, _ = candidate
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["allowed_channels"] = ["card_transfer"]
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="channel"):
        runtime().AMLProbabilityModel(package, offline_candidate=True).predict(
            **observations[0]
        )


def test_candidate_cannot_be_promoted_with_boolean_gates_only(candidate):
    import hashlib

    package, _, _ = candidate
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    evaluation = {
        "gates": {key: True for key in runtime().RELEASE_GATES},
        "release_ready": True,
        "evaluated_split": "test",
        "model_sha256": manifest["artifact_hashes"]["model.cbm"],
        "calibration_sha256": manifest["artifact_hashes"]["calibration.json"],
        "dataset_manifest_sha256": "unbacked-dataset-id",
    }
    (package / "evaluation.json").write_text(json.dumps(evaluation), encoding="utf-8")
    manifest["artifact_hashes"]["evaluation.json"] = hashlib.sha256(
        (package / "evaluation.json").read_bytes()
    ).hexdigest()
    manifest.update(
        release_ready=True,
        status="release-ready",
        dataset_manifest_sha256="unbacked-dataset-id",
        allowed_channels=["bank_transfer", "card_transfer", "cash_withdrawal"],
    )
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="release|Release"):
        runtime().AMLProbabilityModel(package)


def test_calibration_verifier_rejects_empty_predictions_and_claimed_true_support(
    tmp_path,
):
    import hashlib
    from scripts.package_aml_classifier import _verify_calibration
    from scripts.aml_dataset.aml_training import json_bytes

    training = {"artifact_hashes": {"model.cbm": "model-id"}}
    dataset = {"version": "test-fixture"}
    artifacts = {
        "calibration.json": {"method": "none"},
        "selection.json": {
            "selected": "none",
            "low_groups": 0,
            "high_groups": 0,
            "support_gate_passed": True,
        },
        "protocol.json": {},
        "feature-schema.json": {},
        "training-manifest.json": training,
        "dataset-manifest.json": dataset,
    }
    for name, value in artifacts.items():
        (tmp_path / name).write_bytes(json_bytes(value))
    (tmp_path / "calibration-predictions.csv").write_text(
        "scenario_id,group_id,split,aml_label,raw_margin,probability\n"
    )
    sources = [
        "scripts/calibrate_aml_classifier.py",
        "src/aml_workshop_simulator/services/aml_calibration.py",
    ]
    manifest = {
        "version": "aml-calibration-v1",
        "model_sha256": "model-id",
        "accessed_model_splits": ["calibration-fit", "calibration-check"],
        "status": "awaiting-independent-test",
        "source_hashes": {
            n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in sources
        },
        "artifact_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tmp_path.iterdir()
        },
    }
    (tmp_path / "manifest.json").write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match="Calibration"):
        _verify_calibration(tmp_path, training, dataset)


@pytest.mark.parametrize("optimized", [False, True])
def test_runtime_works_without_sklearn_and_guards_survive_optimization(
    candidate, observations, tmp_path, optimized
):
    package, _, _ = candidate
    public = tmp_path / "observation.json"
    public.write_text(json.dumps(observations[0]), encoding="utf-8")
    program = """
import builtins,json,sys
from pathlib import Path
original_import=builtins.__import__
def without_sklearn(name,*args,**kwargs):
    if name=='sklearn' or name.startswith('sklearn.'):
        raise ImportError('sklearn deliberately unavailable for runtime test')
    return original_import(name,*args,**kwargs)
builtins.__import__=without_sklearn
from src.aml_workshop_simulator.services.aml_probability_model import AMLProbabilityModel
package=Path(sys.argv[1])
try:
    AMLProbabilityModel(package)
except ValueError:
    pass
else:
    raise RuntimeError('Candidate incorrectly accepted for production')
result=AMLProbabilityModel(package,offline_candidate=True).predict(**json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
if not 0<=result['aml_probability']<=1 or result['shap_residual']>1e-6:
    raise RuntimeError('Invalid inference')
print(json.dumps({'p':result['aml_probability']}))
"""
    command = (
        [sys.executable]
        + (["-O"] if optimized else [])
        + ["-c", program, str(package), str(public)]
    )
    result = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 0 <= json.loads(result.stdout)["p"] <= 1


@pytest.mark.parametrize("offline_candidate", [False, True])
def test_package_cannot_omit_a_preregistered_demo_profile(
    tmp_path, monkeypatch, offline_candidate
):
    from scripts import package_aml_classifier as package

    training = tmp_path / "training"
    training.mkdir()
    (training / "demo-binding.json").write_text(
        json.dumps({"required_profiles": ["role-a", "role-b"]})
    )
    monkeypatch.setattr(package, "audit_dataset", lambda _: {"release_ready": True})
    monkeypatch.setattr(package, "verify_training_artifact", lambda *_: {})
    with pytest.raises(ValueError, match="demo profile"):
        package.package_classifier(
            training=training,
            calibration=tmp_path / "calibration",
            dataset=tmp_path / "dataset",
            dictionary=tmp_path / "dictionary",
            output=tmp_path / "out",
            allowed_profiles=["role-a"],
            category_allowlist={},
            evaluation=tmp_path / "report",
            offline_candidate=offline_candidate,
        )
    assert not (tmp_path / "out").exists()
