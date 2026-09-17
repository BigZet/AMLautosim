"""Verify every frozen test prediction through the production AML runtime.

This verifies offline/runtime equivalence and serial performance only. It does
not certify browser, database, container, recovery or independent demo checks.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import time

import numpy as np

from scripts.aml_dataset.aml_training import audit_dataset, read_rows
from src.aml_workshop_simulator.schemas.scoring import AMLProbabilityExplanationOut
from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator
from src.aml_workshop_simulator.services.aml_probability_model import (
    AMLProbabilityModel,
    canonical_hash,
)


def require(condition, message):
    if not condition:
        raise ValueError("AML integration verification: " + message)


def read(path):
    return Path(path).read_text(encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_verified_inputs(dataset, package):
    """Production-only boundary; candidates and unaudited data cannot be verified."""
    model = AMLProbabilityModel(package)
    audit = audit_dataset(dataset)
    require(audit["release_ready"] and not audit["unmet_gates"], "dataset not ready")
    require(
        sha(dataset / "manifest.json") == model.manifest["dataset_manifest_sha256"],
        "dataset does not match accepted model",
    )
    reference = json.loads(read(package / "evaluation.json"))
    ids = json.loads(read(package / "test-ids.json"))
    require(
        reference["release_ready"] is True and reference["evaluated_split"] == "test",
        "accepted independent test required",
    )
    require(reference["test_ids"] == ids, "package test roster mismatch")
    for key in ("model_sha256", "calibration_sha256"):
        require(
            reference[key] == model.model_identity[key],
            "evaluation model binding mismatch",
        )
    require(
        reference["dataset_manifest_sha256"]
        == model.manifest["dataset_manifest_sha256"],
        "evaluation dataset binding mismatch",
    )
    rows = [
        row for row in read_rows(dataset / "scenarios.jsonl") if row["split"] == "test"
    ]
    return model, rows, reference


def verify(dataset: Path, package: Path, output: Path) -> dict:
    dataset, package, output = Path(dataset), Path(package), Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing existing verification output: {output}")
    require(
        not any(
            output.resolve().is_relative_to(path.resolve())
            for path in (dataset, package)
        ),
        "report must be outside immutable dataset/package",
    )
    model, rows, reference = load_verified_inputs(dataset, package)
    ids = reference["test_ids"]
    require(
        isinstance(ids, list)
        and all(isinstance(sid, str) and sid for sid in ids)
        and len(set(ids)) == len(ids)
        and len(ids) >= 100,
        "unique frozen test roster with at least 100 rows required",
    )
    by_id = {row["scenario_id"]: row for row in rows}
    require(
        len(by_id) == len(rows) and set(by_id) == set(ids),
        "missing/duplicate test scenarios",
    )
    expected = reference["predictions"]
    require(
        [row["scenario_id"] for row in expected] == ids,
        "offline predictions differ from exact ordered test roster",
    )
    require(
        list(model.classifier.classes_) == [0, 1], "positive class mapping mismatch"
    )
    identity = deepcopy(model.model_identity)
    durations = []
    errors = dict(probability=0.0, raw_margin=0.0, shap=0.0)
    started = time.perf_counter()
    for sid, offline in zip(ids, expected, strict=True):
        row = by_id[sid]
        require(
            row["group_id"] == offline["group_id"]
            and row["aml_label"] == offline["aml_label"],
            "offline labels/groups differ from frozen test",
        )
        require(
            all(
                type(offline[key]) in (int, float) and math.isfinite(offline[key])
                for key in ("probability", "raw_margin")
            )
            and 0 <= offline["probability"] <= 1,
            "nonfinite/out-of-range offline prediction",
        )
        public = deepcopy(row["public_snapshot"])
        before_hash = canonical_hash(public)
        expected_context = canonical_hash(public["config"]["behavior"])
        before = time.perf_counter()
        result = AMLProbabilityExplanationOut.model_validate(model.predict(**public))
        duration = time.perf_counter() - before
        require(math.isfinite(duration) and duration >= 0, "invalid elapsed time")
        durations.append(duration)
        require(
            canonical_hash(public) == before_hash,
            "runtime mutated the frozen observation",
        )
        require(
            result.model_identity.model_dump() == identity
            and model.model_identity == identity,
            "runtime model identity mismatch",
        )
        require(
            result.context_sha256 == expected_context,
            "runtime context identity mismatch",
        )
        require(
            [f.feature for f in result.shap_values] == model.schema["features"],
            "SHAP feature roster/order mismatch",
        )
        residual = abs(
            result.base_margin
            + math.fsum(f.contribution for f in result.shap_values)
            - result.raw_margin
        )
        require(
            residual <= 1e-6 and abs(residual - result.shap_residual) <= 1e-6,
            "SHAP reconstruction exceeds 1e-6",
        )
        require(
            result.calibration.parameters == model.calibrator,
            "calibration identity mismatch",
        )
        raw = float(apply_calibrator([result.raw_margin], {"method": "none"})[0])
        calibrated = float(apply_calibrator([result.raw_margin], model.calibrator)[0])
        require(
            abs(raw - result.uncalibrated_probability) <= 1e-8
            and abs(calibrated - result.aml_probability) <= 1e-8,
            "runtime probability does not match numeric calibration",
        )
        errors["probability"] = max(
            errors["probability"], abs(result.aml_probability - offline["probability"])
        )
        errors["raw_margin"] = max(
            errors["raw_margin"], abs(result.raw_margin - offline["raw_margin"])
        )
        errors["shap"] = max(errors["shap"], residual)
        require(
            errors["probability"] <= 1e-8 and errors["raw_margin"] <= 1e-8,
            "offline/runtime prediction discrepancy exceeds 1e-8",
        )
    first_100 = sum(durations[:100])
    require(first_100 <= 60, "100 sequential explanations exceed 60 seconds")
    report = dict(
        passed=True,
        scope="offline-runtime-test-and-serial-performance-only",
        rows=len(ids),
        test_ids=ids,
        dataset_manifest_sha256=model.manifest["dataset_manifest_sha256"],
        model_identity=identity,
        reference_sha256=canonical_hash(reference),
        verifier_sha256=sha(Path(__file__)),
        max_probability_error=errors["probability"],
        max_raw_margin_error=errors["raw_margin"],
        max_shap_residual=errors["shap"],
        seconds=time.perf_counter() - started,
        first_100_seconds=first_100,
        first_50_seconds=sum(durations[:50]),
        p95_seconds=float(np.quantile(durations, 0.95)),
        environment=dict(
            python=platform.python_version(),
            platform=platform.platform(),
            processor=platform.processor(),
            logical_cpus=os.cpu_count(),
            inference_threads="CatBoost method default; no verifier override",
        ),
    )
    serialized = (
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "package", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.dataset, args.package, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
