"""Offline calibration fitting and prespecified selection on disjoint groups.

Only fitted numeric parameters are exported to the application runtime.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from scripts.aml_classifier import load_splits, verify_training_artifact
from scripts.aml_dataset.aml_provenance import digest
from scripts.aml_dataset.aml_training import audit_dataset, json_bytes
from src.aml_workshop_simulator.services.aml_calibration import (
    apply_calibrator,
    validate_calibrator,
)


def _samples(raw_margin, labels):
    margin, y = np.asarray(raw_margin, dtype=float), np.asarray(labels, dtype=float)
    if margin.ndim != 1 or y.shape != margin.shape or len(y) < 2:
        raise ValueError(
            "Calibration requires aligned nonempty one-dimensional samples"
        )
    if not np.isfinite(margin).all() or not np.isfinite(y).all() or set(y) != {0, 1}:
        raise ValueError("Calibration requires finite margins and both binary classes")
    return margin, y


def fit_calibrator(raw_margin, labels, method) -> dict:
    margin, y = _samples(raw_margin, labels)
    if method == "none":
        return {"method": "none"}
    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression

        fitted = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(
            margin, y
        )
        artifact = {
            "method": "isotonic",
            "x": fitted.X_thresholds_.tolist(),
            "y": fitted.y_thresholds_.tolist(),
            "interpolation": "linear_clamped",
        }
    elif method == "sigmoid":
        # Fit log(a), b so the probability order cannot be reversed by calibration.
        def objective(parameters):
            a = np.exp(parameters[0])
            scaled = a * margin
            z = scaled + parameters[1]
            residual = np.exp(-np.logaddexp(0, -z)) - y
            return np.mean(np.logaddexp(0, z) - y * z), np.array(
                [
                    np.mean(residual * scaled),
                    np.mean(residual),
                ]
            )

        result = minimize(
            objective,
            [0.0, 0.0],
            method="L-BFGS-B",
            jac=True,
            bounds=[(-20.0, 20.0), (-1000.0, 1000.0)],
            options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-9},
        )
        if not result.success or not np.isfinite(result.fun):
            raise ValueError(
                "Sigmoid calibration optimizer failed: " + str(result.message)
            )
        artifact = {
            "method": "sigmoid",
            "a": float(np.exp(result.x[0])),
            "b": float(result.x[1]),
        }
    else:
        raise ValueError("Unsupported calibration method")
    validate_calibrator(artifact)
    return artifact


def _losses(y, p):
    clipped = np.clip(p, np.finfo(float).eps, 1 - np.finfo(float).eps)
    return {
        "log_loss": float(-np.mean(y * np.log(clipped) + (1 - y) * np.log1p(-clipped))),
        "brier": float(np.mean((p - y) ** 2)),
    }


def select_calibrator(
    fit_margin,
    fit_labels,
    check_margin,
    check_labels,
    *,
    fit_groups,
    check_groups,
    fit_observation_hashes,
):
    fit, y_fit = _samples(fit_margin, fit_labels)
    check, y_check = _samples(check_margin, check_labels)
    for values, count in (
        (fit_groups, len(fit)),
        (check_groups, len(check)),
        (fit_observation_hashes, len(fit)),
    ):
        if len(values) != count or any(not isinstance(v, str) or not v for v in values):
            raise ValueError(
                "Calibration group/observation identities must align with samples"
            )
    if set(fit_groups) & set(check_groups):
        raise ValueError("Calibration fit/check group leakage")
    eligible = len(set(fit_observation_hashes)) >= 1000 and len(set(fit_groups)) >= 100
    methods = ["none", "sigmoid"] + (["isotonic"] if eligible else [])
    artifacts, candidates = {}, {}
    for method in methods:
        artifacts[method] = fit_calibrator(fit, y_fit, method)
        candidates[method] = _losses(
            y_check, apply_calibrator(check, artifacts[method])
        )
    baseline = candidates["none"]
    qualified = [
        m
        for m in methods
        if m != "none"
        and baseline["log_loss"] - candidates[m]["log_loss"] >= 0.002 - 1e-12
        and candidates[m]["brier"] <= baseline["brier"] + 0.001 + 1e-12
    ]
    if qualified:
        best = min(candidates[m]["log_loss"] for m in qualified)
        selected = next(
            m
            for m in methods
            if m in qualified and candidates[m]["log_loss"] - best < 0.002 - 1e-12
        )
    else:
        selected = "none"
    p = apply_calibrator(check, artifacts[selected])
    groups = np.asarray(check_groups)
    low_groups = len(set(groups[p < 0.1]))
    high_groups = len(set(groups[p >= 0.9]))
    report = {
        "selected": selected,
        "candidates": candidates,
        "isotonic_eligible": eligible,
        "fit_unique_observations": len(set(fit_observation_hashes)),
        "fit_groups": len(set(fit_groups)),
        "check_groups": len(set(check_groups)),
        "low_groups": low_groups,
        "high_groups": high_groups,
        "support_gate_passed": low_groups >= 20 and high_groups >= 20,
        "thresholds": {"low_exclusive": 0.1, "high_inclusive": 0.9},
    }
    return artifacts[selected], report


def calibrate(dataset: Path, model: Path, protocol: Path, output: Path) -> None:
    from catboost import CatBoostClassifier, Pool

    dataset, model, protocol, output = map(Path, (dataset, model, protocol, output))
    if output.exists():
        raise FileExistsError(f"Refusing existing output: {output}")
    if not audit_dataset(dataset)["release_ready"]:
        raise ValueError("Calibration requires a reviewed release-ready dataset")
    training_manifest = verify_training_artifact(model, dataset)
    rules = json.loads(protocol.read_text(encoding="utf-8"))
    if rules != json.loads((dataset / "protocol.json").read_text(encoding="utf-8")):
        raise ValueError("Calibration protocol differs from frozen dataset")
    schema, data = load_splits(dataset, ("calibration-fit", "calibration-check"))
    classifier = CatBoostClassifier().load_model(str(model / "model.cbm"))
    if (
        classifier.classes_.tolist() != [0, 1]
        or classifier.feature_names_ != schema["features"]
    ):
        raise ValueError("Classifier class/feature schema mismatch")
    categories = [
        name for name in schema["features"] if schema["types"][name] == "categorical"
    ]
    margins = {
        split: np.asarray(
            classifier.predict(
                Pool(row["features"], cat_features=categories),
                prediction_type="RawFormulaVal",
            ),
            dtype=float,
        )
        for split, row in data.items()
    }
    fit, check = data["calibration-fit"], data["calibration-check"]
    artifact, report = select_calibrator(
        margins["calibration-fit"],
        fit["labels"],
        margins["calibration-check"],
        check["labels"],
        fit_groups=fit["groups"],
        check_groups=check["groups"],
        fit_observation_hashes=[
            digest(row) for row in fit["features"].to_dict(orient="records")
        ],
    )
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "calibration.json": artifact,
        "selection.json": report,
        "protocol.json": rules,
        "feature-schema.json": schema,
        "training-manifest.json": training_manifest,
        "dataset-manifest.json": json.loads(
            (dataset / "manifest.json").read_text(encoding="utf-8")
        ),
    }
    for name, value in artifacts.items():
        (output / name).write_bytes(json_bytes(value))
    predictions = []
    for split, samples in data.items():
        probabilities = apply_calibrator(margins[split], artifact)
        for index, sid in enumerate(samples["ids"]):
            predictions.append(
                {
                    "scenario_id": sid,
                    "observation_sha256": digest(
                        samples["features"].iloc[index].to_dict()
                    ),
                    "group_id": samples["groups"][index],
                    "split": split,
                    "aml_label": int(samples["labels"][index]),
                    "raw_margin": float(margins[split][index]),
                    "probability": float(probabilities[index]),
                }
            )
    with (output / "calibration-predictions.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    root = Path(__file__).resolve().parents[1]
    sources = [
        "scripts/calibrate_aml_classifier.py",
        "src/aml_workshop_simulator/services/aml_calibration.py",
    ]
    manifest = {
        "version": "aml-calibration-v1",
        "release_ready": False,
        "status": "awaiting-independent-test"
        if report["support_gate_passed"]
        else "insufficient-calibration-support",
        "accessed_model_splits": ["calibration-fit", "calibration-check"],
        "model_sha256": training_manifest["artifact_hashes"]["model.cbm"],
        "source_hashes": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sources
        },
        "artifact_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
            if p.is_file()
        },
    }
    (output / "manifest.json").write_bytes(json_bytes(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "model", "protocol", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    calibrate(args.dataset, args.model, args.protocol, args.output)


if __name__ == "__main__":
    main()
