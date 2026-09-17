"""Fixed diagnostic model/calibration and a separately frozen control pack.

Never writes a deployable model or modifies game scoring. Control labels are
used only after fitting; test predictions are never produced.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.linear_model import LogisticRegression

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_provenance import neutral_observation
from scripts.audit_aml_history_population import file_hash, require
from scripts.diagnose_aml_fixed_history import metrics


def weights(frame):
    values = 1 / frame.groupby("group_id").group_id.transform("size")
    return (values / values.mean()).to_numpy()


def logits(probability):
    clipped = np.clip(probability, 1e-7, 1 - 1e-7)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def feature_key(row, names, categories):
    return tuple(str(row[n]) if n in categories else float(row[n]) for n in names)


def evaluate(dataset, controls, output):
    require(not output.exists(), "Output already exists")
    freeze = json.loads((controls / "freeze.json").read_bytes())
    require(
        file_hash("scripts/aml_chain_control.py") == freeze["source_sha256"],
        "Control source drift",
    )
    for name, expected in freeze["artifact_hashes"].items():
        require(file_hash(controls / name) == expected, "Control artifact drift")
    receipt = json.loads((dataset / "audit.json").read_bytes())
    for name in ("features.csv", "split.csv", "casebook.jsonl", "context.json"):
        require(
            file_hash(dataset / name) == receipt["artifact_hashes"][name],
            "Dataset drift",
        )
    records = [
        json.loads(line)
        for line in (controls / "casebook.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    control = pd.read_csv(controls / "features.csv").set_index("scenario_id")
    frame = pd.read_csv(dataset / "features.csv")
    names = list(frame.columns.drop("scenario_id"))
    require(names == list(control.columns), "Feature schema drift")
    categories = [n for n in names if not pd.api.types.is_numeric_dtype(frame[n])]
    # Integrity check reads all feature rows, but never predicts on the test set.
    keys = {}
    for sid, row in control.iterrows():
        keys.setdefault(feature_key(row, names, categories), []).append(sid)
    exact = {sid: [] for sid in control.index}
    for row in frame.to_dict("records"):
        for sid in keys.get(feature_key(row, names, categories), []):
            exact[sid].append(row["scenario_id"])
    context = json.loads((dataset / "context.json").read_bytes())
    require(
        all(r["public_snapshot"]["config"] == context for r in records),
        "Context differs",
    )
    shape_context = deepcopy(context)
    shape_context["behavior"]["history"]["operations"] = []

    def shape(steps):
        return p.digest(
            neutral_observation(dict(config=shape_context, steps=steps), shape=True)
        )

    shapes = {}
    for row in records:
        shapes.setdefault(shape(row["public_snapshot"]["steps"]), []).append(
            row["scenario_id"]
        )
    overlap = {sid: [] for sid in control.index}
    with (dataset / "casebook.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            for sid in shapes.get(shape(row["public_snapshot"]["steps"]), []):
                overlap[sid].append(row["scenario_id"])
    print("Control separation audited; fitting fixed diagnostic model", flush=True)
    roster = pd.read_csv(dataset / "split.csv")
    roster = roster[
        roster.split.isin(
            ["train", "validation", "calibration-fit", "calibration-check"]
        )
    ]
    data = roster.merge(frame, on="scenario_id", validate="one_to_one")
    parts = {name: group.copy() for name, group in data.groupby("split")}
    train, fit, check = (
        parts[n] for n in ("train", "calibration-fit", "calibration-check")
    )
    varying = [n for n in names if train[n].nunique() > 1]
    model = CatBoostClassifier(
        iterations=300,
        depth=4,
        learning_rate=0.05,
        l2_leaf_reg=10,
        random_seed=2026091701,
        thread_count=4,
        loss_function="Logloss",
        verbose=False,
        allow_writing_files=False,
        cat_features=[n for n in varying if n in categories],
    )
    model.fit(train[varying], train.aml_label, sample_weight=weights(train))
    calibration = LogisticRegression(C=1.0, random_state=2026091701)
    calibration.fit(
        logits(model.predict_proba(fit[varying])[:, 1]),
        fit.aml_label,
        sample_weight=weights(fit),
    )
    report = dict(
        status="diagnostic_only",
        release_ready=False,
        parameters=dict(
            iterations=300,
            depth=4,
            learning_rate=0.05,
            l2_leaf_reg=10,
            seed=2026091701,
            calibration="Platt on logit, LogisticRegression C=1",
        ),
        partitions_used=dict(
            model_fit="train",
            calibrator_fit="calibration-fit",
            quality_check="calibration-check",
            test_predictions=False,
        ),
        control_freeze_sha256=file_hash(controls / "freeze.json"),
        source_sha256=file_hash(__file__),
        dataset_audit_sha256=file_hash(dataset / "audit.json"),
        calibration=dict(
            slope=float(calibration.coef_[0, 0]),
            intercept=float(calibration.intercept_[0]),
        ),
    )
    raw = model.predict_proba(check[varying])[:, 1]
    calibrated = calibration.predict_proba(logits(raw))[:, 1]
    report["calibration_check"] = dict(
        raw=metrics(check.aml_label.to_numpy(), raw, weights(check)),
        calibrated=metrics(check.aml_label.to_numpy(), calibrated, weights(check)),
    )
    raw = model.predict_proba(control[varying])[:, 1]
    calibrated = calibration.predict_proba(logits(raw))[:, 1]
    lookup = {r["scenario_id"]: r for r in records}
    cases = []
    for sid, before, after in zip(control.index, raw, calibrated):
        row = lookup[sid]
        cases.append(
            dict(
                scenario_id=sid,
                title=row["title"],
                aml_label=row["aml_label"],
                raw=float(before),
                calibrated=float(after),
                exact_feature_overlaps=len(exact[sid]),
                shape_overlaps=len(overlap[sid]),
            )
        )
    report["cases"] = cases
    for name, subset in (
        ("all_labeled_control", [r for r in cases if r["aml_label"] is not None]),
        (
            "nonoverlapping_labeled_control",
            [
                r
                for r in cases
                if r["aml_label"] is not None
                and not r["exact_feature_overlaps"]
                and not r["shape_overlaps"]
            ],
        ),
    ):
        if len({r["aml_label"] for r in subset}) == 2:
            report[name] = dict(
                rows=len(subset),
                raw=metrics(
                    np.array([r["aml_label"] for r in subset]),
                    np.array([r["raw"] for r in subset]),
                    np.ones(len(subset)),
                ),
                calibrated=metrics(
                    np.array([r["aml_label"] for r in subset]),
                    np.array([r["calibrated"] for r in subset]),
                    np.ones(len(subset)),
                ),
            )
    report["limitations"] = [
        "25 stress cases are not a representative prevalence estimate or independent expert review.",
        "Calibration is measured, not assumed to improve quality; it cannot recover hidden ownership.",
        "Control evaluation consumes this freeze for diagnosis; future tuning needs a new untouched acceptance set.",
        "Unresolved cases are excluded from binary metrics; contrary private outcomes may share observations.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(p.json_bytes(report))
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                in (
                    "calibration",
                    "calibration_check",
                    "all_labeled_control",
                    "nonoverlapping_labeled_control",
                )
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.dataset, args.controls, args.output)
