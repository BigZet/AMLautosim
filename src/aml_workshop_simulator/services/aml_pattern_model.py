"""Separate runtime for educational-pattern probability, never criminal probability."""

import hashlib
import json
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier

from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.aml_calibration import (
    apply_calibrator,
    probability_category,
)
from src.aml_workshop_simulator.services.aml_context import evaluate
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features
from src.aml_workshop_simulator.services.aml_pattern_quality import (
    QUALITY_POLICY,
    quality_failures,
)
from src.aml_workshop_simulator.services.aml_pattern_policy import (
    POLICY,
    chain_features,
    label_pattern,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


class AMLPatternModel:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = json.loads((directory / "manifest.json").read_bytes())
        if self.manifest.get("quality_policy") != QUALITY_POLICY:
            raise ValueError(
                "Pattern package uses obsolete quality criteria; grey share must be 10–20%"
            )
        if self.manifest.get("target") != POLICY["target"] or self.manifest.get(
            "policy_sha256"
        ) != digest(POLICY):
            raise ValueError("Wrong pattern target or policy")
        if not self.manifest.get("offline_quality_passed"):
            raise ValueError("Pattern package failed quality checks")
        supported = self.manifest.get("supported_patterns", [])
        if not supported or not set(supported) <= set(POLICY["rules"]):
            raise ValueError("Pattern package has no valid coverage declaration")
        root = Path(__file__).resolve().parents[3]
        sources = self.manifest.get("runtime_source_hashes", {})
        if not sources:
            raise ValueError("Missing runtime source bindings")
        for name, expected in sources.items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Pattern runtime source drift: " + name)
        for name in (
            "model.cbm",
            "calibration.json",
            "schema.json",
            "context.json",
            "evaluation.json",
        ):
            expected = self.manifest["artifact_hashes"].get(name)
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Pattern package artifact mismatch: " + name)
        self.context = json.loads((directory / "context.json").read_bytes())
        evaluation = json.loads((directory / "evaluation.json").read_bytes())
        failures = quality_failures(
            evaluation["partitions"]["test"], representative=True
        )
        failures += quality_failures(
            evaluation["controls"]["metrics"], representative=False
        )
        if failures:
            raise ValueError(
                "Pattern package fails current quality criteria: " + ", ".join(failures)
            )
        self.schema = json.loads((directory / "schema.json").read_bytes())
        self.calibration = json.loads((directory / "calibration.json").read_bytes())
        self.model = CatBoostClassifier()
        self.model.load_model(str(directory / "model.cbm"))
        if (
            list(self.model.classes_) != [0, 1]
            or self.model.feature_names_ != self.schema["features"]
        ):
            raise ValueError("Pattern model classes/features mismatch")

    def predict(self, steps, config):
        if digest(config) != digest(self.context):
            raise ValueError("Pattern model requires the pinned common game context")
        if submit_blockers(evaluate(steps, config)):
            raise ValueError("Chain does not satisfy the game contract")
        observed = chain_features(steps)
        label, matched = label_pattern(observed)
        if label and not set(matched) & set(self.manifest["supported_patterns"]):
            raise ValueError(
                "This standalone pattern is outside the model's training coverage"
            )
        features = {**extract_features(steps, config), **observed}
        row = [features[n] for n in self.schema["features"]]
        margin = self.model.predict([row], prediction_type="RawFormulaVal")
        probability = float(
            np.asarray(apply_calibrator(margin, self.calibration)).reshape(-1)[0]
        )
        if not np.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Invalid pattern probability")
        return dict(
            score_kind="aml_pattern_probability",
            pattern_probability=probability,
            risk_score=round(100 * probability, 2),
            category=probability_category(probability),
            meaning=POLICY["meaning"],
            policy_version=POLICY["version"],
        )
