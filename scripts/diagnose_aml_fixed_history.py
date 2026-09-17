"""Development-only signal diagnostic; never produces a deployable model."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss


def metrics(y, probability, weights):
    low, high = probability < 0.1, probability >= 0.9
    return {
        "log_loss": float(log_loss(y, probability, sample_weight=weights)),
        "roc_auc": float(roc_auc_score(y, probability, sample_weight=weights)),
        "brier": float(brier_score_loss(y, probability, sample_weight=weights)),
        "grey_share": float(np.average(~(low | high), weights=weights)),
        "low_rows": int(low.sum()),
        "high_rows": int(high.sum()),
        "fraud_share_among_low": float(np.average(y[low], weights=weights[low]))
        if low.any()
        else None,
        "lawful_share_among_high": float(np.average(1 - y[high], weights=weights[high]))
        if high.any()
        else None,
    }


def diagnose(root, output, chain_review=False):
    if output.exists():
        raise ValueError("Refusing to overwrite an experiment")
    roster = pd.read_csv(root / "split.csv")
    roster = roster[roster.split.isin(["train", "validation"])]
    ids = set(roster.scenario_id)
    # Discard sealed partitions while streaming; never fit or evaluate them.
    features = pd.concat(
        [
            chunk[chunk.scenario_id.isin(ids)]
            for chunk in pd.read_csv(root / "features.csv", chunksize=2048)
        ],
        ignore_index=True,
    )
    names = list(features.columns.drop("scenario_id"))
    data = roster.merge(features, on="scenario_id", validate="one_to_one")
    assert len(data) == len(roster)
    train = data[data.split == "train"].copy()
    validation = data[data.split == "validation"].copy()
    assert not set(train.group_id) & set(validation.group_id)
    # Equal total weight per connected group, normalized to mean row weight 1.
    for frame in (train, validation):
        frame["weight"] = 1 / frame.groupby("group_id").group_id.transform("size")
        frame["weight"] /= frame.weight.mean()
    varying = [name for name in names if train[name].nunique() > 1]
    proxies = [
        name
        for name in varying
        if any(
            token in name
            for token in (
                "relationship",
                "information",
                "party_",
                "recipient",
                "return_to_sender",
            )
        )
    ]
    y = validation.aml_label.to_numpy()
    weights = validation.weight.to_numpy()
    prior = np.average(train.aml_label, weights=train.weight)
    report = {
        "status": "research_only_not_release_evidence",
        "release_ready": False,
        "partitions_evaluated": ["validation"],
        "sealed_partitions_evaluated": [],
        "seed": 2026091701,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "weighting": "equal total weight per connected group within each split",
        "constant_features": [name for name in names if name not in varying],
        "proxy_features": proxies,
        "baseline": metrics(y, np.full(len(y), prior), weights),
        "runs": {},
        "source_hashes": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("features.csv", "split.csv", "policy.json")
        },
    }
    experiments = [
        ("full", varying),
        ("counterparty_proxies_only", proxies),
        (
            "without_named_counterparty_proxies",
            [n for n in varying if n not in proxies],
        ),
    ]
    if chain_review:
        attributes = [
            n
            for n in varying
            if any(t in n for t in ("relationship", "information", "party_"))
        ]
        temporal = [
            n
            for n in varying
            if any(
                t in n
                for t in ("interval", "elapsed", "gap", "tempo", "fast_", "night")
            )
        ]
        experiments = [
            ("full", varying),
            ("party_attributes_only", attributes),
            ("without_party_attributes", [n for n in varying if n not in attributes]),
            ("timing_only", temporal),
            (
                "without_party_attributes_or_timing",
                [n for n in varying if n not in attributes and n not in temporal],
            ),
        ]
        report["attribute_features"] = attributes
        report["temporal_features"] = temporal
    for label, columns in experiments:
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
            cat_features=[
                n for n in columns if not pd.api.types.is_numeric_dtype(train[n])
            ],
        )
        model.fit(train[columns], train.aml_label, sample_weight=train.weight)
        probability = model.predict_proba(validation[columns])[:, 1]
        report["runs"][label] = {
            "feature_count": len(columns),
            "group_weighted": metrics(y, probability, weights),
            "row_weighted": metrics(y, probability, np.ones(len(y))),
            "top_features": sorted(
                zip(columns, model.feature_importances_.tolist()),
                key=lambda item: -item[1],
            )[:10],
        }
    report["limitations"] = [
        "Labels and class-conditional sampling probabilities are authored assumptions.",
        "Ablation is diagnostic, not causal proof: correlated proxies remain.",
        "No calibration, model selection, deployment, or independent domain approval.",
        "Validation shares generator/template distribution with training.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v["group_weighted"] for k, v in report["runs"].items()}, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chain-review", action="store_true")
    args = parser.parse_args()
    diagnose(args.dataset, args.output, args.chain_review)
