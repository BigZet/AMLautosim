"""Prespecified probability metrics and conservative group uncertainty gates.

These numerical gates alone are not a package release approval: provenance,
subgroup coverage, integration and the frozen demonstration remain mandatory.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import beta
from sklearn.metrics import average_precision_score, roc_auc_score

SEED = 2026091601


def claim_test_access(dataset_identity, candidate_identity, directory):
    """Persist the first frozen candidate; identical reruns are reproducibility only."""
    if any(
        not isinstance(value, str) or not value
        for value in (dataset_identity, candidate_identity)
    ):
        raise ValueError("Nonempty dataset/candidate identities required")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(dataset_identity.encode()).hexdigest() + ".json")
    receipt = {
        "dataset_identity": dataset_identity,
        "candidate_identity": candidate_identity,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True, indent=2)
            handle.write("\n")
    except FileExistsError:
        previous = json.loads(path.read_text(encoding="utf-8"))
        if (
            previous.get("dataset_identity") != dataset_identity
            or previous.get("candidate_identity") != candidate_identity
        ):
            raise ValueError(
                "Independent test already opened for another candidate; a new independent dataset is required"
            )
        return {**previous, "reproduction": True}
    return {**receipt, "reproduction": False}


def evaluate_subgroups(labels, probabilities, groups, dimensions):
    y, p, _ = _inputs(labels, probabilities, np.ones(len(labels)))
    if (
        len(groups) != len(y)
        or any(not isinstance(g, str) or not g for g in groups)
        or not isinstance(dimensions, dict)
        or not dimensions
    ):
        raise ValueError("Aligned groups and nonempty subgroup dimensions required")
    groups = np.asarray(groups)
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    group_weights = 1.0 / counts[inverse]
    slices, allowlist = [], {}
    for axis, memberships in dimensions.items():
        if not isinstance(axis, str) or not axis or len(memberships) != len(y):
            raise ValueError("Subgroup dimensions must align with rows")
        normalized = []
        for membership in memberships:
            values = [membership] if isinstance(membership, str) else membership
            if (
                not isinstance(values, (list, tuple, set))
                or not values
                or any(not isinstance(v, str) or not v for v in values)
            ):
                raise ValueError("Each subgroup membership requires nonempty strings")
            normalized.append(set(values))
        allowlist[axis] = []
        for value in sorted(set().union(*normalized)):
            mask = np.array([value in membership for membership in normalized])
            n = int(mask.sum())
            support = {label: len(set(groups[mask & (y == label)])) for label in (0, 1)}
            supported = n >= 100 and min(support.values()) >= 20
            metrics = {
                "row": probability_metrics(y[mask], p[mask], np.ones(n)),
                "group": probability_metrics(y[mask], p[mask], group_weights[mask]),
            }
            passed = supported and all(
                metric[error] is not None and metric[error] <= 0.1 + 1e-12
                for metric in metrics.values()
                for error in ("false_high", "false_low")
            )
            if passed:
                allowlist[axis].append(value)
            slices.append(
                {
                    "axis": axis,
                    "value": value,
                    "rows": n,
                    "groups": len(set(groups[mask])),
                    "groups_with_class_0": support[0],
                    "groups_with_class_1": support[1],
                    "status": "passed"
                    if passed
                    else "failed"
                    if supported
                    else "insufficient-support",
                    "metrics": metrics,
                }
            )
    return {
        "allowlist": allowlist,
        "slices": slices,
        "passed": all(allowlist.values())
        and all(s["status"] != "failed" for s in slices),
        "scope": "Supported profile/channel slices; insufficient slices are excluded from release allowlist",
    }


def _inputs(labels, probabilities, weights):
    y, p, w = (np.asarray(v, dtype=float) for v in (labels, probabilities, weights))
    if (
        y.ndim != 1
        or not len(y)
        or y.shape != p.shape
        or y.shape != w.shape
        or not all(np.isfinite(v).all() for v in (y, p, w))
        or not set(y).issubset({0, 1})
        or np.any((p < 0) | (p > 1))
        or np.any(w < 0)
        or w.sum() <= 0
    ):
        raise ValueError(
            "Aligned finite binary labels/probabilities and nonnegative weights required"
        )
    return y, p, w


def probability_metrics(labels, probabilities, weights):
    y, p, w = _inputs(labels, probabilities, weights)

    def mean(values, mask=None):
        chosen = np.ones(len(y), dtype=bool) if mask is None else mask
        denominator = w[chosen].sum()
        return (
            float(np.sum(w[chosen] * np.asarray(values)[chosen]) / denominator)
            if denominator
            else None
        )

    low, high = p < 0.1, p >= 0.9
    clipped = np.clip(p, np.finfo(float).eps, 1 - np.finfo(float).eps)
    bins = np.minimum((p * 10).astype(int), 9)
    ece = 0.0
    for index in range(10):
        mask = bins == index
        mass = w[mask].sum()
        if mass:
            ece += mass / w.sum() * abs(mean(y, mask) - mean(p, mask))
    both_classes = all(w[y == label].sum() > 0 for label in (0, 1))
    return {
        "roc_auc": float(roc_auc_score(y, p, sample_weight=w))
        if both_classes
        else None,
        "average_precision": float(average_precision_score(y, p, sample_weight=w))
        if both_classes
        else None,
        "class_prior": mean(y),
        "log_loss": mean(-(y * np.log(clipped) + (1 - y) * np.log1p(-clipped))),
        "brier": mean((p - y) ** 2),
        "ece": float(ece),
        "grey": mean((p >= 0.1) & (p < 0.9)),
        "false_high": mean(high, y == 0),
        "false_low": mean(low, y == 1),
        "precision_high": mean(y, high),
        "npv_low": mean(1 - y, low),
    }


def group_event_bound(events: int, groups: int):
    if type(events) is not int or type(groups) is not int or not 0 <= events <= groups:
        raise ValueError("Group events require integer 0 <= k <= n")
    if not groups:
        return None
    return (
        1.0 if events == groups else float(beta.ppf(0.95, events + 1, groups - events))
    )


def evaluate_probabilities(
    labels, probabilities, groups, *, prior, bootstrap_repeats=2000
):
    y, p, _ = _inputs(labels, probabilities, np.ones(len(labels)))
    if (
        len(groups) != len(y)
        or any(not isinstance(g, str) or not g for g in groups)
        or not np.isfinite(prior)
        or not 0 < prior < 1
        or type(bootstrap_repeats) is not int
        or bootstrap_repeats < 1
    ):
        raise ValueError(
            "Evaluation requires aligned group IDs, finite prior, positive repeat count"
        )
    unique, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    weights = {"row": np.ones(len(y)), "group": 1.0 / counts[inverse]}
    aggregations = {}
    for name, w in weights.items():
        aggregations[name] = {
            "metrics": probability_metrics(y, p, w),
            "constant_prior": probability_metrics(y, np.full(len(y), prior), w),
        }
    rng = np.random.default_rng(SEED)
    draws = {
        name: {key: [] for key in data["metrics"]}
        for name, data in aggregations.items()
    }
    for _ in range(bootstrap_repeats):
        # Selecting an origin carries all its observations, including both labels.
        multiplicity = np.bincount(
            rng.integers(0, len(unique), len(unique)), minlength=len(unique)
        )[inverse]
        for name, w in weights.items():
            sample = probability_metrics(y, p, w * multiplicity)
            for metric, value in sample.items():
                if value is not None:
                    draws[name][metric].append(value)
    for name, metrics in draws.items():
        intervals = {}
        for metric, values in metrics.items():
            fraction = len(values) / bootstrap_repeats
            intervals[metric] = {
                "lower": float(np.quantile(values, 0.025)) if values else None,
                "upper": float(np.quantile(values, 0.975)) if values else None,
                "valid_fraction": fraction,
                "sufficient": fraction >= 0.95,
            }
        aggregations[name]["confidence_intervals"] = intervals

    def group_set(mask):
        return set(inverse[mask].tolist())

    low, high = p < 0.1, p >= 0.9
    masks = {
        "false_high": (y == 0, (y == 0) & high),
        "false_low": (y == 1, (y == 1) & low),
        "high_error_event": (high, high & (y == 0)),
        "low_error_event": (low, low & (y == 1)),
    }
    events = {}
    for name, (eligible, error) in masks.items():
        n, k = len(group_set(eligible)), len(group_set(error))
        events[name] = {
            "groups": n,
            "groups_with_error": k,
            "upper_95": group_event_bound(k, n),
        }
    support = {
        "class_0": len(group_set(y == 0)),
        "class_1": len(group_set(y == 1)),
        "low": len(group_set(low)),
        "high": len(group_set(high)),
    }
    gates = {
        "bootstrap_protocol": bootstrap_repeats == 2000,
        "test_class_group_support": min(support["class_0"], support["class_1"]) >= 60,
        "test_tail_group_support": min(support["low"], support["high"]) >= 30,
    }

    def at_least(value, threshold):
        return value is not None and value >= threshold - 1e-12

    def at_most(value, threshold):
        return value is not None and value <= threshold + 1e-12

    for name, data in aggregations.items():
        m, constant, ci = (
            data["metrics"],
            data["constant_prior"],
            data["confidence_intervals"],
        )
        checks = {
            "roc_auc": at_least(m["roc_auc"], 0.9),
            "average_precision": m["average_precision"] is not None
            and m["average_precision"] > m["class_prior"],
            "log_loss": m["log_loss"] < constant["log_loss"],
            "brier": m["brier"] < constant["brier"],
            "ece": at_most(m["ece"], 0.05),
            "grey": at_most(m["grey"], 0.2),
            "false_high": at_most(m["false_high"], 0.05),
            "false_low": at_most(m["false_low"], 0.05),
            "precision_high": at_least(m["precision_high"], 0.9),
            "npv_low": at_least(m["npv_low"], 0.9),
            "ci_defined": all(v["sufficient"] for v in ci.values()),
            "false_high_ci": at_most(ci["false_high"]["upper"], 0.1),
            "false_low_ci": at_most(ci["false_low"]["upper"], 0.1),
            "precision_high_ci": at_least(ci["precision_high"]["lower"], 0.85),
            "npv_low_ci": at_least(ci["npv_low"]["lower"], 0.85),
        }
        gates.update({name + ":" + key: bool(value) for key, value in checks.items()})
    for name, event in events.items():
        gates["group_event:" + name] = at_most(
            event["upper_95"], 0.15 if name.endswith("error_event") else 0.1
        )
    bins = np.minimum((p * 10).astype(int), 9)
    reliability = []
    for index in range(10):
        mask = bins == index
        count = int(mask.sum())
        group_count = len(group_set(mask))
        reliability.append(
            {
                "lower": index / 10,
                "upper": (index + 1) / 10,
                "upper_inclusive": index == 9,
                "rows": count,
                "groups": group_count,
                "support": "supported" if group_count >= 30 else "insufficient-support",
                "predicted": float(p[mask].mean()) if count else None,
                "observed": float(y[mask].mean()) if count else None,
                "group_weighted_predicted": float(
                    np.average(p[mask], weights=weights["group"][mask])
                )
                if count
                else None,
                "group_weighted_observed": float(
                    np.average(y[mask], weights=weights["group"][mask])
                )
                if count
                else None,
            }
        )
    return {
        "release_ready": all(gates.values()),
        "scope": "main-test-quantitative-gates-only",
        "reference_prior": float(prior),
        "rows": len(y),
        "groups": len(unique),
        "support": support,
        "thresholds": {"low_exclusive": 0.1, "high_inclusive": 0.9},
        "bootstrap": {
            "repeats": bootstrap_repeats,
            "seed": SEED,
            "unit": "provenance-group",
            "interval": "95%-percentile",
        },
        "aggregations": aggregations,
        "group_events": events,
        "reliability": reliability,
        "gates": gates,
    }


# Public artifact helpers live separately to keep the numerical gates inspectable.
from scripts.aml_evaluation_artifacts import (  # noqa: E402
    prediction_report,
    prior_sensitivity,
    write_evaluation_artifacts,
)


def score_rows(model, rows):
    """Score every supplied frozen observation; retain unresolved labels verbatim."""
    import pandas as pd
    from catboost import Pool
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    if not rows:
        return []
    ids = [r["scenario_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate scoring observation ID")
    features = [model.feature_vector(**row["public_snapshot"]) for row in rows]
    frame = pd.DataFrame(features, columns=model.schema["features"])
    categories = [
        n for n in model.schema["features"] if model.schema["types"][n] == "categorical"
    ]
    margins = np.asarray(
        model.classifier.predict(
            Pool(frame, cat_features=categories), prediction_type="RawFormulaVal"
        )
    )
    p = apply_calibrator(margins, model.calibrator)
    if not np.isfinite(margins).all():
        raise ValueError("Nonfinite native margins")
    return [
        {
            "scenario_id": row["scenario_id"],
            "group_id": row["group_id"],
            "aml_label": row["aml_label"],
            "raw_margin": float(margins[i]),
            "probability": float(p[i]),
        }
        for i, row in enumerate(rows)
    ]


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError("Evaluation provenance: " + message)


def verify_upstream_sources(stage, hashes):
    sources = {
        "training": {
            "scripts/aml_classifier.py",
            "scripts/train_aml_classifier.py",
            "scripts/training_environment.py",
            "scripts/aml_demo_training.py",
        },
        "calibration": {
            "scripts/calibrate_aml_classifier.py",
            "src/aml_workshop_simulator/services/aml_calibration.py",
        },
    }
    _require(
        stage in sources and isinstance(hashes, dict) and set(hashes) == sources[stage],
        "incorrect upstream source roster",
    )
    root = Path(__file__).resolve().parents[1]
    _require(
        all(_file_hash(root / name) == expected for name, expected in hashes.items()),
        stage + " source mismatch",
    )


def _verify_candidate(dataset, package, model):
    """Reject raw experiments and mismatched upstream artifacts before test scoring."""
    from scripts.aml_dataset.aml_training import audit_dataset

    manifest = model.manifest
    hashes = manifest["artifact_hashes"]
    required = {
        "dataset-manifest.json",
        "dataset-audit.json",
        "test-ids.json",
        "training-manifest.json",
        "training-selection.json",
        "training-stability.json",
        "training-baselines.json",
        "calibration-manifest.json",
        "calibration-selection.json",
    }
    _require(
        required <= set(hashes),
        "candidate is not bound to reviewed training/calibration provenance",
    )
    audit = audit_dataset(dataset)
    _require(
        audit.get("release_ready") is True and audit.get("unmet_gates") == [],
        "dataset is not release-ready",
    )
    _require(
        _read(dataset / "manifest.json").get("release_ready") is True,
        "dataset manifest is not release-ready",
    )
    for local, packaged in [
        ("manifest.json", "dataset-manifest.json"),
        ("audit.json", "dataset-audit.json"),
        ("feature-schema.json", "feature-schema.json"),
        ("protocol.json", "protocol.json"),
    ]:
        _require(
            _file_hash(dataset / local) == hashes[packaged],
            "dataset/package artifact binding mismatch: " + local,
        )
    _require(
        manifest.get("dataset_manifest_sha256")
        == _file_hash(dataset / "manifest.json"),
        "dataset manifest binding mismatch",
    )
    training = _read(package / "training-manifest.json")
    calibration = _read(package / "calibration-manifest.json")
    for name, source in [("training", training), ("calibration", calibration)]:
        _require(
            manifest.get(name + "_manifest_sha256") == hashes[name + "-manifest.json"],
            name + " manifest binding mismatch",
        )
        verify_upstream_sources(name, source.get("source_hashes"))
        for artifact in (
            "dataset-manifest.json",
            "feature-schema.json",
            "protocol.json",
        ):
            _require(
                source.get("artifact_hashes", {}).get(artifact) == hashes[artifact],
                name + " upstream artifact mismatch",
            )
    _require(
        training.get("status") == "awaiting-calibration-and-evaluation"
        and training.get("accessed_model_splits") == ["train", "validation"],
        "training protocol mismatch",
    )
    _require(
        calibration.get("status") == "awaiting-independent-test"
        and calibration.get("accessed_model_splits")
        == ["calibration-fit", "calibration-check"],
        "calibration protocol mismatch",
    )
    for original, target in [
        ("model.cbm", "model.cbm"),
        ("selection.json", "training-selection.json"),
        ("stability.json", "training-stability.json"),
        ("baselines.json", "training-baselines.json"),
    ]:
        _require(
            training["artifact_hashes"].get(original) == hashes[target],
            "training artifact binding mismatch: " + original,
        )
    for original, target in [
        ("calibration.json", "calibration.json"),
        ("selection.json", "calibration-selection.json"),
        ("training-manifest.json", "training-manifest.json"),
    ]:
        _require(
            calibration["artifact_hashes"].get(original) == hashes[target],
            "calibration artifact binding mismatch: " + original,
        )
    _require(
        calibration.get("model_sha256") == hashes["model.cbm"],
        "calibration/model mismatch",
    )
    stability = _read(package / "training-stability.json")
    runs = stability.get("runs", [])
    _require(
        stability.get("passed") is True
        and [r.get("seed") for r in runs] == [SEED, SEED + 1, SEED + 2],
        "training stability protocol failed",
    )
    for metric in ("roc_auc", "false_high", "false_low"):
        values = [r.get(metric) for r in runs]
        _require(
            all(
                type(v) in (float, int) and np.isfinite(v) and 0 <= v <= 1
                for v in values
            )
            and max(values) - min(values) <= 0.03 + 1e-12,
            "training stability failed",
        )
    return audit


def _reproduce_calibration(dataset, package, model):
    from catboost import Pool
    from scripts.aml_classifier import load_splits
    from scripts.aml_dataset.aml_provenance import digest
    from scripts.calibrate_aml_classifier import select_calibrator

    schema, samples = load_splits(dataset, ("calibration-fit", "calibration-check"))
    _require(schema == model.schema, "calibration schema mismatch")
    cats = [n for n in schema["features"] if schema["types"][n] == "categorical"]
    margins = {
        s: np.asarray(
            model.classifier.predict(
                Pool(d["features"], cat_features=cats), prediction_type="RawFormulaVal"
            )
        )
        for s, d in samples.items()
    }
    fit, check = samples["calibration-fit"], samples["calibration-check"]
    artifact, selection = select_calibrator(
        margins["calibration-fit"],
        fit["labels"],
        margins["calibration-check"],
        check["labels"],
        fit_groups=fit["groups"],
        check_groups=check["groups"],
        fit_observation_hashes=[
            digest(r) for r in fit["features"].to_dict(orient="records")
        ],
    )
    _require(
        artifact == model.calibrator
        and selection == _read(package / "calibration-selection.json")
        and selection["support_gate_passed"] is True,
        "calibration cannot be reproduced from frozen calibration splits",
    )
    return selection


def frozen_test_identity(dataset):
    """Bind test values and group membership, ignoring cosmetic serialization changes.

    Integrity scan only; no prediction, fitting or selection uses this material.
    Diagnostic descendants may rename derived groups without changing test evidence.
    """
    import csv
    from collections import defaultdict
    from src.aml_workshop_simulator.services.aml_probability_model import canonical_hash

    dataset = Path(dataset)
    schema = _read(dataset / "feature-schema.json")
    names = schema["features"]
    types = schema["types"]
    _require(
        len(names) == len(set(names))
        and set(types) == set(names)
        and set(types.values()) <= {"numeric", "categorical"},
        "invalid test feature schema",
    )
    with (dataset / "split.csv").open(encoding="utf-8", newline="") as handle:
        roster = [r for r in csv.DictReader(handle) if r["split"] == "test"]
    ids = {r["scenario_id"] for r in roster}
    _require(bool(ids) and len(ids) == len(roster), "missing/duplicate test identity")
    groups = defaultdict(list)
    for row in roster:
        _require(
            row["aml_label"] in {"0", "1"} and bool(row["group_id"]),
            "invalid test label/group",
        )
        groups[row["group_id"]].append(row["scenario_id"])
    normalized_roster = [
        {
            "scenario_id": row["scenario_id"],
            "aml_label": int(row["aml_label"]),
            "group_members": sorted(groups[row["group_id"]]),
        }
        for row in roster
    ]
    with (dataset / "features.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _require(
            reader.fieldnames == ["scenario_id", *names],
            "test feature columns mismatch",
        )
        features = [r for r in reader if r["scenario_id"] in ids]
    _require(
        len(features) == len(ids) and {r["scenario_id"] for r in features} == ids,
        "missing/duplicate test observations",
    )
    for row in features:
        for name in names:
            if types[name] == "numeric":
                value = float(row[name])
                _require(np.isfinite(value), "nonfinite test observation")
                row[name] = 0.0 if value == 0 else value
            else:
                _require(
                    isinstance(row[name], str) and bool(row[name]),
                    "missing categorical test observation",
                )
    return canonical_hash(
        {
            "feature_types": types,
            "roster": sorted(normalized_roster, key=lambda r: r["scenario_id"]),
            "observations": sorted(features, key=lambda r: r["scenario_id"]),
        }
    )


def evaluate_challenges(dataset, model):
    """Keep diagnostics separate and expose unavailable/unsupported evidence as failed."""
    from scripts.aml_dataset.aml_training import read_rows

    challenges = {}
    for name in ("masked-context", "unresolved", "new-combinations", "family-held-out"):
        diagnostic = name in ("masked-context", "unresolved")
        relative = ("diagnostics/" if diagnostic else "challenges/") + name + ".jsonl"
        path = Path(dataset) / relative
        records = read_rows(path) if path.is_file() else []
        try:
            report = prediction_report(score_rows(model, records))
        except ValueError as error:
            # Do not discard the troublesome observations or fabricate predictions.
            report = {
                "status": "failed",
                "rows": len(records),
                "predictions_sha256": None,
                "reason": str(error),
                "scenario_ids": [r["scenario_id"] for r in records],
            }
        challenges[name] = {
            **report,
            "independent": not diagnostic,
            "scope": "Non-independent diagnostic; never pooled with main test"
            if diagnostic
            else "Preregistered independent held-out provenance groups",
            "dataset_artifact": relative,
        }
    return challenges


def evaluate(dataset: Path, package: Path, split: str) -> dict:
    """One frozen-candidate experiment; exact repetition is reproduction only."""
    from catboost import Pool
    from scripts.aml_ablations import fit_ablations
    from scripts.aml_classifier import load_splits, positive_probabilities
    from scripts.aml_dataset.aml_training import read_rows
    from src.aml_workshop_simulator.services.aml_probability_model import (
        AMLProbabilityModel,
        canonical_hash,
    )

    if split != "test":
        raise ValueError("Independent evaluation requires split=test")
    dataset, package = Path(dataset), Path(package)
    model = AMLProbabilityModel(package, offline_candidate=True)
    audit = _verify_candidate(dataset, package, model)
    calibration = _reproduce_calibration(dataset, package, model)
    schema, train_data = load_splits(dataset, ("train",))
    training = train_data["train"]
    prior = float(np.mean(training["labels"]))
    _require(
        prior == _read(package / "training-baselines.json")["constant_prior"]["prior"],
        "frozen training prior mismatch",
    )
    selected = _read(package / "training-selection.json")
    _require(
        selected.get("trees") == model.classifier.tree_count_,
        "selected tree count mismatch",
    )
    parameters = model.classifier.get_all_params()
    _require(
        all(parameters.get(k) == selected.get(k) for k in ("depth", "l2_leaf_reg")),
        "selected model parameters mismatch",
    )
    ablations = fit_ablations(training, schema, selected)
    sources = {
        name: _file_hash(Path(__file__).parent / name)
        for name in (
            "evaluate_aml_classifier.py",
            "aml_evaluation_artifacts.py",
            "aml_ablations.py",
        )
    }
    identity = canonical_hash(
        {
            "model": model.model_identity,
            "sources": sources,
            "ablation_parameters": {
                k: {"features": v["features"], "parameters": v["parameters"]}
                for k, v in ablations.items()
            },
        }
    )
    receipt = claim_test_access(
        frozen_test_identity(dataset),
        identity,
        Path(__file__).resolve().parents[1] / ".local-run" / "aml-test-access",
    )
    # First access for model evaluation happens only after calibration and train-only fitting.
    test_schema, splits = load_splits(dataset, ("test",))
    test = splits["test"]
    _require(test_schema == schema, "test schema mismatch")
    _require(
        test["ids"] == _read(package / "test-ids.json"),
        "test roster differs from bound package",
    )
    all_rows = {r["scenario_id"]: r for r in read_rows(dataset / "scenarios.jsonl")}
    rows = [all_rows[sid] for sid in test["ids"]]
    _require(
        [r["aml_label"] for r in rows] == test["labels"].tolist()
        and [r["group_id"] for r in rows] == test["groups"],
        "test metadata mismatch",
    )
    predictions = score_rows(model, rows)
    p = [r["probability"] for r in predictions]
    main = evaluate_probabilities(test["labels"], p, test["groups"], prior=prior)
    channels = [
        sorted(
            {
                s.get("action_details", {}).get("incoming_kind", s["card"]["code"])
                for s in r["public_snapshot"]["steps"]
            }
        )
        for r in rows
    ]
    subgroups = evaluate_subgroups(
        test["labels"],
        p,
        test["groups"],
        {
            "profile": [
                r["public_snapshot"]["config"]["behavior"]["profile"]["id"]
                for r in rows
            ],
            "channel": channels,
        },
    )
    ablation_reports = {}
    for name, fitted in ablations.items():
        features = fitted["features"]
        cats = [n for n in features if schema["types"][n] == "categorical"]
        probabilities = positive_probabilities(
            fitted["model"], Pool(test["features"][features], cat_features=cats)
        )
        records = [
            {**r, "probability": float(probabilities[i])}
            for i, r in enumerate(predictions)
        ]
        for record in records:
            record.pop("raw_margin")  # Primary model margins are not ablation margins.
        ablation_reports[name] = {
            **prediction_report(records),
            "features": features,
            "parameters": fitted["parameters"],
            "calibration": fitted["calibration"],
            "scope": fitted["scope"],
        }
    # Audit ensures challenge files are frozen, recomputed and manifest-bound.
    challenges = evaluate_challenges(dataset, model)
    gates = {
        "dataset_provenance": True,
        "main_test": main["release_ready"],
        "subgroups": subgroups["passed"],
        "challenge_reports": all(
            r["status"] == "complete" for r in challenges.values()
        ),
        "ablation_reports": all(
            r["status"] == "complete" for r in ablation_reports.values()
        ),
    }
    return {
        "version": "aml-evaluation-v1",
        "evaluated_split": "test",
        "release_ready": all(gates.values()),
        "gates": gates,
        "dataset_manifest_sha256": model.manifest["dataset_manifest_sha256"],
        "model_sha256": model.model_identity["model_sha256"],
        "calibration_sha256": model.model_identity["calibration_sha256"],
        "model_identity": model.model_identity,
        "source_hashes": sources,
        "test_access": receipt,
        "test_ids": test["ids"],
        "predictions": predictions,
        "prediction_summary": prediction_report(predictions),
        "main_test": main,
        "subgroups": subgroups,
        "challenge_reports": challenges,
        "ablation_reports": ablation_reports,
        "dataset_audit": audit,
        "coverage": _read(dataset / "coverage.json"),
        "collisions": _read(dataset / "collisions.json"),
        "calibration_selection": calibration,
        "prior_sensitivity": prior_sensitivity(predictions, prior),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "package", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--split", required=True, choices=["test"])
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".artifacts").exists():
        raise FileExistsError(f"Refusing existing evaluation output: {args.output}")
    report = evaluate(args.dataset, args.package, args.split)
    write_evaluation_artifacts(report, args.output)
    return 0 if report["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
