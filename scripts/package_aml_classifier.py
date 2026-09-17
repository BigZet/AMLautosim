"""Create immutable AML candidates or packages backed by completed release gates."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from scripts.aml_classifier import load_splits, verify_training_artifact
from scripts.aml_dataset.aml_provenance import digest
from scripts.aml_dataset.aml_training import audit_dataset, json_bytes
from src.aml_workshop_simulator.services.aml_calibration import (
    apply_calibrator,
    validate_calibrator,
)
from src.aml_workshop_simulator.services.aml_contract import fixed_financial_contract
from src.aml_workshop_simulator.services.aml_probability_model import (
    AMLProbabilityModel,
    RELEASE_GATES,
    THRESHOLDS,
    canonical_hash,
    current_source_hashes,
    validate_schema,
)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_package(
    *,
    model,
    calibrator,
    schema,
    protocol,
    dictionary,
    allowed_profiles,
    category_allowlist,
    output,
    evaluation,
    ready=False,
    binding=None,
    extra=None,
):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing existing output: {output}")
    validate_schema(schema)
    validate_calibrator(calibrator)
    model_bytes = Path(model).read_bytes()
    files = {
        "model.cbm": model_bytes,
        "calibration.json": json_bytes(calibrator),
        "feature-schema.json": json_bytes(schema),
        "protocol.json": json_bytes(protocol),
        "dictionary.json": json_bytes(dictionary),
        "thresholds.json": json_bytes(THRESHOLDS),
        "evaluation.json": json_bytes(evaluation),
    }
    for name, value in (extra or {}).items():
        if name in files or Path(name).name != name:
            raise ValueError("Invalid additional package artifact")
        files[name] = json_bytes(value)
    manifest = {
        "version": "aml-probability-package-v1",
        "task": "binary_classification",
        "positive_class": 1,
        "classes": [0, 1],
        "score_kind": "aml_probability",
        "contract_version": 10,
        "extractor_version": schema["version"],
        "population_id": protocol["population_id"],
        "label_protocol_version": protocol["version"],
        "release_ready": ready,
        "status": "release-ready" if ready else "pending-evaluation",
        "allowed_profiles": allowed_profiles,
        "category_allowlist": category_allowlist,
        "financial_rules_sha256": canonical_hash(fixed_financial_contract()),
        "source_hashes": current_source_hashes(),
        "artifact_hashes": {
            name: hashlib.sha256(data).hexdigest() for name, data in files.items()
        },
        **(binding or {}),
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / "manifest.json").write_bytes(json_bytes(manifest))
    # Native CBM/class/schema checks occur before the caller can claim packaging succeeded.
    AMLProbabilityModel(output, offline_candidate=not ready)


def create_candidate_package(
    *,
    model,
    calibrator,
    schema,
    protocol,
    dictionary,
    allowed_profiles,
    category_allowlist,
    output,
):
    """Raw-model experiments only: always unvalidated, never production-loadable."""
    _write_package(
        model=model,
        calibrator=calibrator,
        schema=schema,
        protocol=protocol,
        dictionary=dictionary,
        allowed_profiles=allowed_profiles,
        category_allowlist=category_allowlist,
        output=output,
        evaluation={
            "version": "aml-evaluation-v1",
            "release_ready": False,
            "status": "not-evaluated",
            "scope": "unvalidated raw-model candidate",
        },
    )


def _verify_calibration(
    directory,
    training_manifest,
    dataset_manifest,
    *,
    dataset_path=None,
    model_path=None,
):
    directory = Path(directory)
    manifest = _read(directory / "manifest.json")
    required = {
        "calibration.json",
        "selection.json",
        "protocol.json",
        "feature-schema.json",
        "training-manifest.json",
        "dataset-manifest.json",
        "calibration-predictions.csv",
    }
    hashes = manifest.get("artifact_hashes", {})
    if set(hashes) != required or {
        p.name for p in directory.iterdir() if p.is_file()
    } != required | {"manifest.json"}:
        raise ValueError("Incomplete or unexpected calibration artifact")
    for name, expected in hashes.items():
        if _sha(directory / name) != expected:
            raise ValueError(f"Calibration artifact checksum mismatch: {name}")
    root = Path(__file__).resolve().parents[1]
    sources = {
        "scripts/calibrate_aml_classifier.py",
        "src/aml_workshop_simulator/services/aml_calibration.py",
    }
    if set(manifest.get("source_hashes", {})) != sources or any(
        _sha(root / name) != expected
        for name, expected in manifest["source_hashes"].items()
    ):
        raise ValueError("Calibration source checksum mismatch")
    if (
        manifest.get("version") != "aml-calibration-v1"
        or manifest.get("model_sha256")
        != training_manifest["artifact_hashes"]["model.cbm"]
        or manifest.get("accessed_model_splits")
        != ["calibration-fit", "calibration-check"]
        or _read(directory / "training-manifest.json") != training_manifest
        or _read(directory / "dataset-manifest.json") != dataset_manifest
    ):
        raise ValueError("Calibration belongs to another training run or dataset")
    if (
        manifest.get("status") != "awaiting-independent-test"
        or _read(directory / "selection.json").get("support_gate_passed") is not True
    ):
        raise ValueError("Calibration support gate failed")
    if dataset_path is None or model_path is None:
        raise ValueError(
            "Calibration verification requires the frozen dataset and native model"
        )
    _validate_calibration_predictions(directory, dataset_path, model_path)
    return manifest


def _validate_calibration_predictions(directory, dataset_path, model_path):
    from catboost import CatBoostClassifier, Pool

    selection = _read(directory / "selection.json")
    artifact = _read(directory / "calibration.json")
    with (directory / "calibration-predictions.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    if not rows or len({r.get("scenario_id") for r in rows}) != len(rows):
        raise ValueError("Calibration requires unique nonempty predictions")
    if any(
        not r.get("scenario_id")
        or not r.get("group_id")
        or not r.get("observation_sha256")
        or r.get("aml_label") not in {"0", "1"}
        or r.get("split") not in {"calibration-fit", "calibration-check"}
        for r in rows
    ):
        raise ValueError("Calibration prediction identities/labels/splits are invalid")
    schema, samples = load_splits(
        Path(dataset_path), ("calibration-fit", "calibration-check")
    )
    model = CatBoostClassifier().load_model(str(model_path))
    categories = [
        name for name in schema["features"] if schema["types"][name] == "categorical"
    ]
    expected = {}
    for split, data in samples.items():
        native_margins = np.asarray(
            model.predict(
                Pool(data["features"], cat_features=categories),
                prediction_type="RawFormulaVal",
            )
        )
        for index, sid in enumerate(data["ids"]):
            expected[sid] = {
                "split": split,
                "group_id": data["groups"][index],
                "aml_label": str(data["labels"][index]),
                "observation_sha256": digest(data["features"].iloc[index].to_dict()),
                "raw_margin": float(native_margins[index]),
            }
    if {r["scenario_id"] for r in rows} != set(expected):
        raise ValueError("Calibration prediction roster differs from frozen dataset")
    for row in rows:
        actual = expected[row["scenario_id"]]
        if any(
            row[key] != actual[key]
            for key in ("split", "group_id", "aml_label", "observation_sha256")
        ) or not np.isclose(
            float(row["raw_margin"]), actual["raw_margin"], atol=1e-8, rtol=0
        ):
            raise ValueError(
                "Calibration prediction provenance/features/native margin mismatch"
            )
    margin = np.asarray([float(r["raw_margin"]) for r in rows])
    p = np.asarray([float(r["probability"]) for r in rows])
    if (
        not np.isfinite(p).all()
        or np.any((p < 0) | (p > 1))
        or not np.allclose(p, apply_calibrator(margin, artifact), atol=1e-12, rtol=0)
        or selection.get("selected") != artifact["method"]
    ):
        raise ValueError("Calibration predictions do not match selected calibrator")
    subsets = {
        split: [r for r in rows if r["split"] == split]
        for split in ("calibration-fit", "calibration-check")
    }
    group_sets = {
        split: {r["group_id"] for r in subset} for split, subset in subsets.items()
    }
    if (
        any(
            {r["aml_label"] for r in subset} != {"0", "1"}
            for subset in subsets.values()
        )
        or group_sets["calibration-fit"] & group_sets["calibration-check"]
    ):
        raise ValueError("Calibration class support or group separation failed")
    check_rows = subsets["calibration-check"]
    low = len({r["group_id"] for r in check_rows if float(r["probability"]) < 0.1})
    high = len({r["group_id"] for r in check_rows if float(r["probability"]) >= 0.9})
    fit_unique = len({r["observation_sha256"] for r in subsets["calibration-fit"]})
    if (
        low < 20
        or high < 20
        or selection.get("low_groups") != low
        or selection.get("high_groups") != high
        or selection.get("fit_groups") != len(group_sets["calibration-fit"])
        or selection.get("check_groups") != len(group_sets["calibration-check"])
        or selection.get("fit_unique_observations") != fit_unique
        or (
            artifact["method"] == "isotonic"
            and (fit_unique < 1000 or len(group_sets["calibration-fit"]) < 100)
        )
    ):
        raise ValueError(
            "Calibration reported support disagrees with prediction groups"
        )


def package_classifier(
    *,
    training,
    calibration,
    dataset,
    dictionary,
    output,
    allowed_profiles,
    category_allowlist,
    evaluation=None,
    offline_candidate=False,
):
    training, calibration, dataset, output = map(
        Path, (training, calibration, dataset, output)
    )
    if output.exists():
        raise FileExistsError(f"Refusing existing output: {output}")
    if type(offline_candidate) is not bool:
        raise ValueError("Explicit boolean offline_candidate required")
    if not offline_candidate and evaluation is None:
        raise ValueError("Production package requires completed independent evaluation")
    if not audit_dataset(dataset)["release_ready"]:
        raise ValueError("Packaging requires a reviewed release-ready dataset")
    training_manifest = verify_training_artifact(training, dataset)
    required_profiles = _read(training / "demo-binding.json").get("required_profiles")
    if (
        not isinstance(required_profiles, list)
        or not required_profiles
        or any(not isinstance(value, str) or not value for value in required_profiles)
        or not set(required_profiles) <= set(allowed_profiles)
    ):
        raise ValueError("Package must retain every preregistered demo profile")
    dataset_manifest = _read(dataset / "manifest.json")
    calibration_manifest = _verify_calibration(
        calibration,
        training_manifest,
        dataset_manifest,
        dataset_path=dataset,
        model_path=training / "model.cbm",
    )
    for name in ("protocol.json", "feature-schema.json"):
        if _read(calibration / name) != _read(training / name):
            raise ValueError("Calibration schema/protocol mismatch")
    binding = {
        "dataset_manifest_sha256": _sha(dataset / "manifest.json"),
        "training_manifest_sha256": _sha(training / "manifest.json"),
        "calibration_manifest_sha256": _sha(calibration / "manifest.json"),
    }
    with (dataset / "split.csv").open(encoding="utf-8", newline="") as handle:
        test_ids = [
            row["scenario_id"]
            for row in csv.DictReader(handle)
            if row["split"] == "test"
        ]
    report = (
        _read(evaluation)
        if evaluation is not None
        else {
            "version": "aml-evaluation-v1",
            "release_ready": False,
            "status": "not-evaluated",
        }
    )
    if not offline_candidate:
        gates = report.get("gates", {})
        with (dataset / "split.csv").open(encoding="utf-8", newline="") as handle:
            test_ids = [
                row["scenario_id"]
                for row in csv.DictReader(handle)
                if row["split"] == "test"
            ]
        if (
            report.get("version") != "aml-evaluation-v1"
            or report.get("evaluated_split") != "test"
            or report.get("release_ready") is not True
            or set(gates) != RELEASE_GATES
            or not all(value is True for value in gates.values())
            or report.get("test_ids") != test_ids
            or report.get("dataset_manifest_sha256")
            != binding["dataset_manifest_sha256"]
            or report.get("model_sha256") != _sha(training / "model.cbm")
            or report.get("calibration_sha256")
            != _sha(calibration / "calibration.json")
        ):
            raise ValueError(
                "Independent release evaluation missing, failed or bound to another artifact"
            )
        main, subgroups = report.get("main_test", {}), report.get("subgroups", {})
        if (
            main.get("scope") != "main-test-quantitative-gates-only"
            or main.get("release_ready") is not True
            or not main.get("gates")
            or not all(v is True for v in main["gates"].values())
            or subgroups.get("passed") is not True
            or not set(allowed_profiles)
            <= set(subgroups.get("allowlist", {}).get("profile", []))
        ):
            raise ValueError("Main-test gates or profile support failed")
        binding["allowed_channels"] = subgroups["allowlist"].get("channel", [])
    _write_package(
        model=training / "model.cbm",
        calibrator=_read(calibration / "calibration.json"),
        schema=_read(training / "feature-schema.json"),
        protocol=_read(training / "protocol.json"),
        dictionary=_read(dictionary),
        allowed_profiles=allowed_profiles,
        category_allowlist=category_allowlist,
        output=output,
        evaluation=report,
        ready=not offline_candidate,
        binding=binding,
        extra={
            "dataset-manifest.json": dataset_manifest,
            "dataset-audit.json": _read(dataset / "audit.json"),
            "test-ids.json": test_ids,
            "training-stability.json": _read(training / "stability.json"),
            "calibration-selection.json": _read(calibration / "selection.json"),
            "training-selection.json": _read(training / "selection.json"),
            "training-baselines.json": _read(training / "baselines.json"),
            "training-manifest.json": training_manifest,
            "calibration-manifest.json": calibration_manifest,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "training",
        "calibration",
        "dataset",
        "dictionary",
        "output",
        "allowlist",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--offline-candidate", action="store_true")
    args = parser.parse_args()
    allowlist = _read(args.allowlist)
    package_classifier(
        training=args.training,
        calibration=args.calibration,
        dataset=args.dataset,
        dictionary=args.dictionary,
        output=args.output,
        evaluation=args.evaluation,
        allowed_profiles=allowlist["profiles"],
        category_allowlist=allowlist["categories"],
        offline_candidate=args.offline_candidate,
    )


if __name__ == "__main__":
    main()
