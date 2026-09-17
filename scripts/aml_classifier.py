"""Strict, test-independent helpers for the AML binary training protocol."""

import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.aml_dataset.aml_training import audit_dataset, json_bytes
from scripts.aml_demo_training import verify_frozen_demo
from scripts.training_environment import collect_training_environment

SEED = 2026091601
TRAINING_PROTOCOL = {
    "loss_function": "Logloss",
    "task_type": "CPU",
    "thread_count": 4,
    "random_seed": SEED,
    "iterations": 3000,
    "learning_rate": 0.04,
    "early_stopping_rounds": 150,
    "depth": [4, 6, 8],
    "l2_leaf_reg": [3, 10],
    "selection_tolerance": 0.002,
    "stability_seeds": [SEED, SEED + 1, SEED + 2],
}


def positive_probabilities(model, data) -> np.ndarray:
    classes = np.asarray(model.classes_)
    if classes.shape != (2,) or set(classes.tolist()) != {0, 1}:
        raise ValueError("Model classes must be exactly binary 0 and 1")
    probabilities = np.asarray(model.predict_proba(data), dtype=float)
    if (
        probabilities.ndim != 2
        or probabilities.shape[1] != 2
        or not np.isfinite(probabilities).all()
        or np.any((probabilities < 0) | (probabilities > 1))
        or not np.allclose(probabilities.sum(axis=1), 1, atol=1e-8, rtol=0)
    ):
        raise ValueError("Invalid binary probabilities")
    return probabilities[:, int(np.flatnonzero(classes == 1)[0])]


def validated_features(frame: pd.DataFrame, schema: dict) -> pd.DataFrame:
    names, types = schema["features"], schema["types"]
    if (
        not names
        or len(set(names)) != len(names)
        or list(frame.columns) != names
        or set(types) != set(names)
    ):
        raise ValueError("Feature columns must exactly match ordered schema")
    for name in names:
        series = frame[name]
        if types[name] == "numeric":
            if (
                not pd.api.types.is_numeric_dtype(series)
                or pd.api.types.is_bool_dtype(series)
                or not np.isfinite(series.to_numpy(dtype=float)).all()
            ):
                raise ValueError(f"Feature {name} must contain finite numeric values")
        elif types[name] == "categorical":
            if not series.map(lambda v: isinstance(v, str) and bool(v)).all():
                raise ValueError(f"Feature {name} must contain nonempty strings")
        else:
            raise ValueError(f"Unsupported feature type for {name}")
    return frame


def select_candidate(candidates: list[dict]) -> dict:
    if not candidates:
        raise ValueError("No training candidates")
    for candidate in candidates:
        if not math.isfinite(candidate["validation_log_loss"]):
            raise ValueError("Candidate loss must be finite")
        if (
            candidate["depth"] not in (4, 6, 8)
            or candidate["l2_leaf_reg"] not in (3, 10)
            or not 1 <= candidate["trees"] <= 3000
        ):
            raise ValueError("Candidate lies outside frozen training grid")
    best = min(c["validation_log_loss"] for c in candidates)
    eligible = [
        c for c in candidates if c["validation_log_loss"] - best <= 0.002 + 1e-12
    ]
    return min(eligible, key=lambda c: (c["depth"], c["trees"], -c["l2_leaf_reg"]))


def seed_stability(runs: list[dict]) -> dict:
    if len(runs) != 3:
        raise ValueError("Stability requires three prespecified seeds")
    spreads = {}
    for name in ("roc_auc", "false_high", "false_low"):
        values = np.asarray([run[name] for run in runs], dtype=float)
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise ValueError("Stability metrics must be finite probabilities")
        spreads[name] = float(np.ptp(values))
    return {
        "passed": all(v <= 0.03 + 1e-12 for v in spreads.values()),
        "spreads": spreads,
        "maximum_spread": 0.03,
    }


def load_development(dataset: Path):
    return load_splits(dataset, ("train", "validation"))


def load_splits(dataset: Path, selected_splits):
    """Select IDs before parsing values: held-out rows never enter model inputs."""
    allowed = {"train", "validation", "calibration-fit", "calibration-check", "test"}
    if (
        not selected_splits
        or len(set(selected_splits)) != len(selected_splits)
        or not set(selected_splits) <= allowed
    ):
        raise ValueError("Explicit known split names required")
    schema = json.loads((dataset / "feature-schema.json").read_text(encoding="utf-8"))
    metadata = {}
    group_splits = {}
    with (dataset / "split.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            group, split = row["group_id"], row["split"]
            if group in group_splits and group_splits[group] != split:
                raise ValueError("Dataset group crosses splits")
            group_splits[group] = split
            if split not in selected_splits:
                continue
            sid = row["scenario_id"]
            if sid in metadata or row["aml_label"] not in {"0", "1"}:
                raise ValueError("Duplicate development ID or nonbinary label")
            metadata[sid] = row
    records = {}
    with (dataset / "features.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["scenario_id", *schema["features"]]:
            raise ValueError("Feature CSV differs from ordered schema")
        for row in reader:
            sid = row.pop("scenario_id")
            if sid not in metadata:
                continue
            if sid in records:
                raise ValueError("Duplicate development feature row")
            records[sid] = {
                name: float(value) if schema["types"][name] == "numeric" else value
                for name, value in row.items()
            }
    if records.keys() != metadata.keys():
        raise ValueError("Missing development features")
    result = {}
    for split in selected_splits:
        ids = [sid for sid, row in metadata.items() if row["split"] == split]
        y = np.array([int(metadata[sid]["aml_label"]) for sid in ids])
        if set(y) != {0, 1}:
            raise ValueError(f"Both binary classes required in {split}")
        result[split] = {
            "ids": ids,
            "groups": [metadata[sid]["group_id"] for sid in ids],
            "labels": y,
            "features": validated_features(
                pd.DataFrame([records[sid] for sid in ids]), schema
            ),
        }
    return schema, result


def verify_training_artifact(directory: Path, dataset: Path):
    directory, dataset = Path(directory), Path(dataset)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    required = {
        "model.cbm",
        "feature-schema.json",
        "class-mapping.json",
        "stability.json",
        "dataset-manifest.json",
        "protocol.json",
        "training-protocol.json",
        "baselines.json",
        "demo-binding.json",
        "demo-freeze/manifest.json",
        "demo-freeze/casebook.json",
        "demo-freeze/records.jsonl",
        "demo-freeze/provenance.json",
        "demo-freeze/protocol.json",
    }
    hashes = manifest.get("artifact_hashes", {})
    if not required <= set(hashes):
        raise ValueError("Incomplete training artifact")
    for name, expected in hashes.items():
        path = directory / name
        if (
            not path.resolve().is_relative_to(directory.resolve())
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"Training artifact checksum mismatch: {name}")
    if {
        p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()
    } != set(hashes) | {"manifest.json"}:
        raise ValueError("Unexpected training artifact files")
    root = Path(__file__).resolve().parents[1]
    expected_sources = {
        "scripts/aml_classifier.py",
        "scripts/train_aml_classifier.py",
        "scripts/training_environment.py",
        "scripts/aml_demo_training.py",
    }
    if set(manifest.get("source_hashes", {})) != expected_sources:
        raise ValueError("Missing training source checksum")
    for name, expected in manifest["source_hashes"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Training source checksum mismatch")

    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    if (
        read("dataset-manifest.json")
        != json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
        or read("feature-schema.json")
        != json.loads((dataset / "feature-schema.json").read_text(encoding="utf-8"))
        or read("protocol.json")
        != json.loads((dataset / "protocol.json").read_text(encoding="utf-8"))
    ):
        raise ValueError("Training artifact belongs to another dataset/schema/protocol")
    demo_binding, _ = verify_frozen_demo(
        directory / "demo-freeze", dataset / "casebook.jsonl"
    )
    if read("demo-binding.json") != demo_binding:
        raise ValueError("Training frozen demo binding mismatch")
    if (
        manifest.get("task") != "binary_classification"
        or manifest.get("positive_class") != 1
        or manifest.get("accessed_model_splits") != ["train", "validation"]
        or manifest.get("status") != "awaiting-calibration-and-evaluation"
        or not read("stability.json").get("passed")
        or read("training-protocol.json") != TRAINING_PROTOCOL
        or read("class-mapping.json") != {"classes": [0, 1], "positive_class": 1}
    ):
        raise ValueError("Training protocol, class mapping or stability gate failed")
    return manifest


def classification_metrics(y, p):
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        log_loss,
        roc_auc_score,
    )

    y, p = np.asarray(y), np.asarray(p)
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "false_high": float(np.mean(p[y == 0] >= 0.9)),
        "false_low": float(np.mean(p[y == 1] < 0.1)),
        "grey": float(np.mean((p >= 0.1) & (p < 0.9))),
    }


def train(
    dataset: Path, protocol: Path, output: Path, *, frozen_demo: Path | None = None
) -> None:
    from catboost import CatBoostClassifier, Pool
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    dataset, protocol, output = Path(dataset), Path(protocol), Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing existing output: {output}")
    audit = audit_dataset(dataset)
    if not audit["release_ready"]:
        raise ValueError("Training requires a reviewed release-ready dataset")
    if frozen_demo is None:
        raise ValueError("Training requires a reviewed frozen demo before fitting")
    demo_binding, demo_snapshot = verify_frozen_demo(
        frozen_demo, dataset / "casebook.jsonl"
    )
    rules = json.loads(protocol.read_text(encoding="utf-8"))
    if rules != json.loads((dataset / "protocol.json").read_text(encoding="utf-8")):
        raise ValueError("Training protocol differs from frozen dataset protocol")
    schema, development = load_development(dataset)
    categories = [n for n in schema["features"] if schema["types"][n] == "categorical"]
    numeric = [n for n in schema["features"] if schema["types"][n] == "numeric"]
    train_data, validation = development["train"], development["validation"]
    pools = {
        split: Pool(data["features"], label=data["labels"], cat_features=categories)
        for split, data in development.items()
    }
    # Preserve the exact checked bytes before even the baseline is fitted.
    # Failure can leave diagnostics here, never a success manifest.
    output.mkdir(parents=True, exist_ok=False)
    (output / "demo-freeze").mkdir()
    for name, raw in demo_snapshot.items():
        (output / "demo-freeze" / name).write_bytes(raw)
    (output / "demo-binding.json").write_bytes(json_bytes(demo_binding))
    prior = float(np.mean(train_data["labels"]))
    logistic = make_pipeline(
        ColumnTransformer(
            [
                ("numeric", StandardScaler(), numeric),
                ("categorical", OneHotEncoder(handle_unknown="ignore"), categories),
            ]
        ),
        LogisticRegression(max_iter=5000, random_state=SEED),
    )
    logistic.fit(train_data["features"], train_data["labels"])
    baseline = {
        "constant_prior": {
            "prior": prior,
            **classification_metrics(
                validation["labels"], np.full(len(validation["labels"]), prior)
            ),
        },
        "logistic": classification_metrics(
            validation["labels"],
            positive_probabilities(logistic, validation["features"]),
        ),
    }
    (output / "candidates").mkdir()
    candidates = []
    base_parameters = {
        k: TRAINING_PROTOCOL[k]
        for k in (
            "loss_function",
            "task_type",
            "thread_count",
            "iterations",
            "learning_rate",
        )
    }

    def fit(depth, l2, seed):
        model = CatBoostClassifier(
            **base_parameters,
            depth=depth,
            l2_leaf_reg=l2,
            random_seed=seed,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(
            pools["train"],
            eval_set=pools["validation"],
            early_stopping_rounds=150,
            use_best_model=True,
        )
        p = positive_probabilities(model, pools["validation"])
        metrics = classification_metrics(validation["labels"], p)
        return model, metrics

    for depth in TRAINING_PROTOCOL["depth"]:
        for l2 in TRAINING_PROTOCOL["l2_leaf_reg"]:
            model, metrics = fit(depth, l2, SEED)
            name = f"d{depth}-l2{l2}.cbm"
            model.save_model(str(output / "candidates" / name))
            candidates.append(
                {
                    "depth": depth,
                    "l2_leaf_reg": l2,
                    "trees": model.tree_count_,
                    "validation_log_loss": metrics["log_loss"],
                    "metrics": metrics,
                    "model": name,
                }
            )
    chosen = select_candidate(candidates)
    selected = CatBoostClassifier().load_model(
        str(output / "candidates" / chosen["model"])
    )
    selected.save_model(str(output / "model.cbm"))
    runs = [{"seed": SEED, **chosen["metrics"]}]
    for seed in (SEED + 1, SEED + 2):
        model, metrics = fit(chosen["depth"], chosen["l2_leaf_reg"], seed)
        model.save_model(str(output / "candidates" / f"stability-{seed}.cbm"))
        runs.append({"seed": seed, **metrics})
    stability = {**seed_stability(runs), "runs": runs}
    predictions = []
    for split, data in development.items():
        p = positive_probabilities(selected, pools[split])
        margin = np.asarray(
            selected.predict(pools[split], prediction_type="RawFormulaVal")
        )
        for index, sid in enumerate(data["ids"]):
            predictions.append(
                {
                    "scenario_id": sid,
                    "group_id": data["groups"][index],
                    "split": split,
                    "aml_label": int(data["labels"][index]),
                    "raw_margin": float(margin[index]),
                    "raw_probability": float(p[index]),
                }
            )
    inventory, environment = collect_training_environment()
    artifacts = {
        "feature-schema.json": schema,
        "protocol.json": rules,
        "training-protocol.json": TRAINING_PROTOCOL,
        "class-mapping.json": {
            "classes": selected.classes_.tolist(),
            "positive_class": 1,
        },
        "candidates.json": candidates,
        "selection.json": chosen,
        "baselines.json": baseline,
        "stability.json": stability,
        "environment.json": environment,
        "dataset-manifest.json": json.loads(
            (dataset / "manifest.json").read_text(encoding="utf-8")
        ),
    }
    for name, value in artifacts.items():
        (output / name).write_bytes(json_bytes(value))
    (output / "installed-packages.txt").write_text(inventory, encoding="utf-8")
    with (output / "development-predictions.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    root = Path(__file__).resolve().parents[1]
    sources = [
        "scripts/aml_classifier.py",
        "scripts/train_aml_classifier.py",
        "scripts/training_environment.py",
        "scripts/aml_demo_training.py",
    ]
    manifest = {
        "task": "binary_classification",
        "positive_class": 1,
        "status": "awaiting-calibration-and-evaluation"
        if stability["passed"]
        else "unstable",
        "release_ready": False,
        "accessed_model_splits": ["train", "validation"],
        "source_hashes": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sources
        },
        "artifact_hashes": {
            p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    (output / "manifest.json").write_bytes(json_bytes(manifest))
