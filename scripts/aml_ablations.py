"""Prespecified feature-block diagnostics; never used to select the released model."""

import numpy as np

from scripts.aml_classifier import validated_features
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import FEATURE_NAMES


def feature_blocks():
    scoped = [
        name
        for name in FEATURE_NAMES
        if name.startswith(
            (
                "explained_",
                "explanation_",
                "unknown_",
                "unverified_",
                "contradicted_",
                "mismatched_",
                "context_",
                "purpose_",
                "activity_",
                "expected_",
                "opening_balance_",
            )
        )
    ]
    return {
        "without_scoped_evidence": [
            name for name in FEATURE_NAMES if name not in scoped
        ],
        "scoped_context_only": scoped,
    }


def fit_ablations(training, schema, selection):
    from catboost import CatBoostClassifier, Pool

    frame = validated_features(training["features"], schema)
    labels = np.asarray(training["labels"])
    if labels.shape != (len(frame),) or set(labels) != {0, 1}:
        raise ValueError(
            "Ablations require aligned training labels of both binary classes"
        )
    if (
        schema["features"] != list(FEATURE_NAMES)
        or selection.get("depth") not in (4, 6, 8)
        or selection.get("l2_leaf_reg") not in (3, 10)
        or type(selection.get("trees")) is not int
        or not 1 <= selection["trees"] <= 3000
    ):
        raise ValueError(
            "Ablations require frozen v5 schema and selected training parameters"
        )
    parameters = {
        "loss_function": "Logloss",
        "task_type": "CPU",
        "thread_count": 4,
        "random_seed": 2026091601,
        "iterations": selection["trees"],
        "learning_rate": 0.04,
        "depth": selection["depth"],
        "l2_leaf_reg": selection["l2_leaf_reg"],
        "verbose": False,
        "allow_writing_files": False,
    }
    result = {}
    for name, features in feature_blocks().items():
        categories = [n for n in features if schema["types"][n] == "categorical"]
        model = CatBoostClassifier(**parameters)
        model.fit(Pool(frame[features], label=labels, cat_features=categories))
        result[name] = {
            "model": model,
            "features": features,
            "parameters": dict(parameters),
            "calibration": {"method": "none"},
            "scope": "Train-only fit; fixed primary hyperparameters/tree count; raw probabilities; not candidate selection",
        }
    return result
