"""Native inference equivalence and real CLI rejection; no release approval fixture."""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from scripts import verify_aml_integration as verifier
from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator
from src.aml_workshop_simulator.services.aml_probability_model import (
    AMLProbabilityModel,
)
from tests.ml.test_aml_probability_model import candidate, observations  # noqa: F401


def test_verifier_compares_native_batch_with_100_real_runtime_explanations(
    candidate,  # noqa: F811
    observations,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    package, native, pool = candidate
    model = AMLProbabilityModel(package, offline_candidate=True)
    # Isolate release evidence only. This tiny model and repeated observations
    # exercise native numerical equivalence, never independent data/quality gates.
    model.manifest["dataset_manifest_sha256"] = "a" * 64
    margins = np.asarray(native.predict(pool, prediction_type="RawFormulaVal"))
    probabilities = apply_calibrator(margins, model.calibrator)
    rows = [
        dict(
            scenario_id=f"unit-{i}",
            group_id=f"fixture-{i % len(observations)}",
            aml_label=i % 2,
            split="test",
            public_snapshot=deepcopy(observations[i % len(observations)]),
        )
        for i in range(100)
    ]
    reference = dict(
        test_ids=[r["scenario_id"] for r in rows],
        predictions=[
            dict(
                scenario_id=r["scenario_id"],
                group_id=r["group_id"],
                aml_label=r["aml_label"],
                probability=float(probabilities[i % len(observations)]),
                raw_margin=float(margins[i % len(observations)]),
            )
            for i, r in enumerate(rows)
        ],
    )
    monkeypatch.setattr(
        verifier, "load_verified_inputs", lambda *args: (model, rows, reference)
    )
    report = verifier.verify(
        tmp_path / "dataset", package, tmp_path / "unit-report.json"
    )
    assert report["rows"] == 100
    assert report["max_probability_error"] <= 1e-8
    assert report["max_raw_margin_error"] <= 1e-8
    assert report["max_shap_residual"] <= 1e-6
    assert report["first_100_seconds"] <= 60


@pytest.mark.parametrize("mode", ["normal", "flag", "environment"])
def test_real_cli_rejects_candidate_in_each_python_optimization_mode(
    candidate,  # noqa: F811
    tmp_path,
    mode,
):
    package, _, _ = candidate
    output = tmp_path / (mode + ".json")
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("PYTHONOPTIMIZE", None)
    if mode == "environment":
        env["PYTHONOPTIMIZE"] = "1"
    command = [sys.executable]
    if mode == "flag":
        command.append("-O")
    command += [
        "-m",
        "scripts.verify_aml_integration",
        "--dataset",
        str(tmp_path / "dataset"),
        "--package",
        str(package),
        "--output",
        str(output),
    ]
    completed = subprocess.run(
        command,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode != 0
    assert "release" in completed.stderr.lower()
    assert not output.exists()
