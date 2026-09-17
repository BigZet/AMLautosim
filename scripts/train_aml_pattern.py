"""Train a surrogate of the explicit teaching policy, not of hidden criminality."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.linear_model import LogisticRegression

from scripts.aml_dataset import aml_population_author as p
from scripts.audit_aml_history_population import file_hash, require
from scripts.evaluate_aml_chain_control import weights
from scripts.diagnose_aml_fixed_history import metrics
from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator
from src.aml_workshop_simulator.services.aml_pattern_policy import (
    POLICY,
    chain_features,
    label_pattern,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features
from src.aml_workshop_simulator.services.aml_pattern_quality import (
    QUALITY_POLICY,
    quality_failures,
)


def pattern_metrics(y, probability, weight):
    result = metrics(np.asarray(y), probability, weight)
    result["grey_row_share"] = float(
        np.mean((probability >= 0.1) & (probability < 0.9))
    )
    result["pattern_share_among_low"] = result.pop("fraud_share_among_low")
    result["nonpattern_share_among_high"] = result.pop("lawful_share_among_high")
    result["agreement"] = float(np.average((probability >= 0.5) == y, weights=weight))
    return result


def train(dataset, controls, output):
    require(not output.exists(), "Model output already exists")
    audit = json.loads((dataset / "audit.json").read_bytes())
    require(audit["target"] == POLICY["target"], "Wrong label target")
    for name, expected in audit["artifact_hashes"].items():
        require(file_hash(dataset / name) == expected, "Dataset artifact drift")
    require(
        json.loads((dataset / "policy.json").read_bytes()) == POLICY, "Policy drift"
    )
    frame = pd.read_csv(dataset / "features.csv").merge(
        pd.read_csv(dataset / "split.csv"), on="scenario_id", validate="one_to_one"
    )
    require(frame.groupby("group_id")["split"].nunique().max() == 1, "Group leakage")
    parts = {name: group for name, group in frame.groupby("split")}
    train_data, fit, check, test = [
        parts[n] for n in ("train", "calibration-fit", "calibration-check", "test")
    ]
    excluded = {"scenario_id", "group_id", "split", "pattern_label"}
    names = [
        n for n in frame.columns if n not in excluded and train_data[n].nunique() > 1
    ]
    categories = [n for n in names if not pd.api.types.is_numeric_dtype(train_data[n])]
    model = CatBoostClassifier(
        iterations=600,
        depth=6,
        learning_rate=0.05,
        l2_leaf_reg=5,
        random_seed=2026091702,
        thread_count=4,
        loss_function="Logloss",
        cat_features=categories,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(
        train_data[names], train_data.pattern_label, sample_weight=weights(train_data)
    )
    calibration_model = LogisticRegression(C=1.0, random_state=2026091702)
    calibration_model.fit(
        model.predict(fit[names], prediction_type="RawFormulaVal").reshape(-1, 1),
        fit.pattern_label,
        sample_weight=weights(fit),
    )
    candidate = dict(
        method="sigmoid",
        a=float(calibration_model.coef_[0, 0]),
        b=float(calibration_model.intercept_[0]),
    )
    margin = model.predict(check[names], prediction_type="RawFormulaVal")
    raw_metrics = pattern_metrics(
        check.pattern_label,
        apply_calibrator(margin, {"method": "none"}),
        weights(check),
    )
    calibrated_metrics = pattern_metrics(
        check.pattern_label, apply_calibrator(margin, candidate), weights(check)
    )
    calibration = (
        candidate
        if calibrated_metrics["brier"] <= raw_metrics["brier"]
        and calibrated_metrics["log_loss"] <= raw_metrics["log_loss"]
        else {"method": "none"}
    )
    evaluation = dict(
        target=POLICY["target"],
        calibration_check=dict(raw=raw_metrics, sigmoid=calibrated_metrics),
        selected_calibration=calibration,
        partitions={},
        interpretation="Agreement with explicit educational rules; not validation against criminal outcomes",
    )
    predictions = {}
    for name in ("validation", "test"):
        part = parts[name]
        probability = apply_calibrator(
            model.predict(part[names], prediction_type="RawFormulaVal"), calibration
        )
        evaluation["partitions"][name] = pattern_metrics(
            part.pattern_label, probability, weights(part)
        )
        predictions.update(
            {sid: float(value) for sid, value in zip(part.scenario_id, probability)}
        )
    # Control private labels are intentionally not read as new target labels.
    freeze = json.loads((controls / "freeze.json").read_bytes())
    for name, expected in freeze["artifact_hashes"].items():
        require(file_hash(controls / name) == expected, "Control drift")
    cases = []
    for line in (controls / "casebook.jsonl").read_text(encoding="utf-8").splitlines():
        old = json.loads(line)
        steps, context = (
            old["public_snapshot"]["steps"],
            old["public_snapshot"]["config"],
        )
        extra = chain_features(steps)
        label, matched = label_pattern(extra)
        values = {**extract_features(steps, context), **extra}
        margin = model.predict(
            [[values[n] for n in names]], prediction_type="RawFormulaVal"
        )
        probability = float(apply_calibrator(margin, calibration)[0])
        cases.append(
            dict(
                scenario_id=old["scenario_id"],
                title=old["title"],
                pattern_label=label,
                matched_patterns=matched,
                probability=probability,
            )
        )
    evaluation["controls"] = dict(
        cases=cases,
        metrics=pattern_metrics(
            np.array([r["pattern_label"] for r in cases]),
            np.array([r["probability"] for r in cases]),
            np.ones(len(cases)),
        ),
    )

    failures = quality_failures(evaluation["partitions"]["test"], representative=True)
    failures += quality_failures(
        evaluation["controls"]["metrics"], representative=False
    )
    evaluation["quality_policy"] = QUALITY_POLICY
    evaluation["quality_failures"] = failures
    passed = not failures
    output.mkdir(parents=True)
    model.save_model(str(output / "model.cbm"))
    (output / "calibration.json").write_bytes(p.json_bytes(calibration))
    (output / "schema.json").write_bytes(
        p.json_bytes(
            dict(
                version="aml-pattern-observable-v1",
                features=names,
                categorical=categories,
            )
        )
    )
    (output / "context.json").write_bytes((dataset / "context.json").read_bytes())
    (output / "evaluation.json").write_bytes(p.json_bytes(evaluation))
    examples = []
    wanted = {0: 10, 1: 10}
    with (dataset / "casebook.jsonl").open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            probability = predictions.get(row["scenario_id"])
            label = row["pattern_label"]
            if probability is None or not wanted[label]:
                continue
            if (label == 0 and probability < 0.1) or (
                label == 1 and probability >= 0.9
            ):
                examples.append(dict(**row, probability=probability))
                wanted[label] -= 1
    (output / "examples.json").write_bytes(p.json_bytes(examples))
    runtime_sources = [
        "src/aml_workshop_simulator/services/aml_pattern_quality.py",
        "src/aml_workshop_simulator/services/aml_pattern_policy.py",
        "src/aml_workshop_simulator/services/aml_pattern_model.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v5.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v4.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v3.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v2.py",
        "src/aml_workshop_simulator/services/aml_calibration.py",
        "src/aml_workshop_simulator/services/aml_context.py",
        "src/aml_workshop_simulator/services/semantic_contract.py",
    ]
    manifest = dict(
        quality_policy=QUALITY_POLICY,
        supported_patterns=sorted(audit["patterns"]),
        deferred_patterns=sorted(set(POLICY["rules"]) - set(audit["patterns"])),
        runtime_source_hashes={name: file_hash(name) for name in runtime_sources},
        target=POLICY["target"],
        score_kind="aml_pattern_probability",
        policy_sha256=p.digest(POLICY),
        offline_quality_passed=passed,
        production_enabled=False,
        dataset_audit_sha256=file_hash(dataset / "audit.json"),
        source_sha256=file_hash(__file__),
        artifact_hashes={
            name: file_hash(output / name)
            for name in (
                "model.cbm",
                "calibration.json",
                "schema.json",
                "context.json",
                "evaluation.json",
                "examples.json",
            )
        },
    )
    (output / "manifest.json").write_bytes(p.json_bytes(manifest))
    print(
        json.dumps(
            dict(
                offline_quality_passed=passed,
                selected_calibration=calibration,
                test=evaluation["partitions"]["test"],
                controls=evaluation["controls"]["metrics"],
                example_count=len(examples),
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    train(args.dataset, args.controls, args.output)
