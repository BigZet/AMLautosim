"""Fail-closed v10 binary probability runtime; no training or pickle dependency."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier, Pool

from src.aml_workshop_simulator.schemas.round_config import AMLGameConfigOut
from src.aml_workshop_simulator.services.aml_calibration import (
    apply_calibrator,
    probability_category,
    validate_calibrator,
)
from src.aml_workshop_simulator.services.aml_contract import (
    financial_projection,
    fixed_financial_contract,
)
from src.aml_workshop_simulator.services.aml_context import validate_config
from src.aml_workshop_simulator.services.aml_release_validation import (
    validate_release_artifacts,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    extract_features,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_FILES = (
    "src/aml_workshop_simulator/services/aml_release_validation.py",
    "src/aml_workshop_simulator/services/aml_probability_model.py",
    "src/aml_workshop_simulator/services/aml_contract.py",
    "src/aml_workshop_simulator/services/aml_calibration.py",
    "src/aml_workshop_simulator/services/aml_context.py",
    "src/aml_workshop_simulator/services/semantic_contract.py",
    "src/aml_workshop_simulator/services/aml_dataset_features_v5.py",
    "src/aml_workshop_simulator/services/aml_dataset_features_v4.py",
    "src/aml_workshop_simulator/services/aml_dataset_features_v3.py",
    "src/aml_workshop_simulator/services/aml_dataset_features_v2.py",
    "src/aml_workshop_simulator/services/aml_episodes.py",
    "src/aml_workshop_simulator/services/counterparties.py",
    "src/aml_workshop_simulator/domain/simulation.py",
    "src/aml_workshop_simulator/domain/operation_timeline.py",
    "src/aml_workshop_simulator/domain/round_policy.py",
    "src/aml_workshop_simulator/domain/catalog.py",
    "src/aml_workshop_simulator/domain/game_models.py",
    "src/aml_workshop_simulator/core/expanded_game.py",
    "src/aml_workshop_simulator/schemas/aml_context.py",
    "src/aml_workshop_simulator/schemas/expanded_contract.py",
    "src/aml_workshop_simulator/schemas/round_config.py",
    "src/aml_workshop_simulator/schemas/scenarios.py",
    "config/base_round.json",
    "config/resource_rules.json",
    "config/operations.json",
    "config/parameters.json",
    "config/expanded_operations.json",
    "config/expanded_behavior.json",
)
REQUIRED_ARTIFACTS = {
    "model.cbm",
    "calibration.json",
    "feature-schema.json",
    "dictionary.json",
    "protocol.json",
    "thresholds.json",
    "evaluation.json",
}
THRESHOLDS = {"low_exclusive": 0.1, "high_inclusive": 0.9}
RELEASE_GATES = {
    "dataset_provenance",
    "main_test",
    "subgroups",
    "challenge_reports",
    "ablation_reports",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value):
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def current_source_hashes():
    return {name: sha256((ROOT / name).read_bytes()) for name in SOURCE_FILES}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def validate_schema(schema):
    check(isinstance(schema, dict), "Feature schema must be an object")
    check(
        schema.get("version") == FEATURE_VERSION
        and schema.get("features") == list(FEATURE_NAMES),
        "Feature schema must exactly match ordered v5 allowlist",
    )
    check(
        schema.get("types")
        == {
            n: "categorical" if n in CATEGORICAL_FEATURES else "numeric"
            for n in FEATURE_NAMES
        },
        "Feature schema types mismatch",
    )


class AMLProbabilityModel:
    def __init__(self, package: Path, *, offline_candidate=False):
        check(
            type(offline_candidate) is bool,
            "offline_candidate must be an explicit boolean",
        )
        package = Path(package)
        self.manifest = json.loads(
            (package / "manifest.json").read_text(encoding="utf-8")
        )
        manifest = self.manifest
        check(
            manifest.get("version") == "aml-probability-package-v1",
            "Unsupported package version",
        )
        check(
            manifest.get("task") == "binary_classification"
            and manifest.get("positive_class") == 1
            and manifest.get("classes") == [0, 1]
            and manifest.get("score_kind") == "aml_probability",
            "Invalid binary class mapping",
        )
        check(
            manifest.get("contract_version") == 10
            and manifest.get("extractor_version") == FEATURE_VERSION,
            "Unsupported model contract",
        )
        ready = manifest.get("release_ready") is True
        check(
            ready or offline_candidate,
            "Package has not passed release gates; offline candidate requires explicit opt-in",
        )
        check(
            ready or manifest.get("status") == "pending-evaluation",
            "Invalid candidate package status",
        )
        hashes = manifest.get("artifact_hashes", {})
        check(REQUIRED_ARTIFACTS <= set(hashes), "Missing required artifact checksum")
        actual_files = {
            p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()
        }
        check(
            actual_files == set(hashes) | {"manifest.json"},
            "Unexpected or missing package artifact checksum",
        )
        for name, expected in hashes.items():
            path = package / name
            check(
                path.resolve().is_relative_to(package.resolve()) and path.is_file(),
                "Invalid artifact path",
            )
            check(
                sha256(path.read_bytes()) == expected,
                f"Artifact checksum mismatch: {name}",
            )
        check(
            manifest.get("source_hashes") == current_source_hashes(),
            "Runtime source checksum mismatch",
        )

        def read(name):
            return json.loads((package / name).read_text(encoding="utf-8"))

        self.schema = read("feature-schema.json")
        validate_schema(self.schema)
        self.calibrator = read("calibration.json")
        validate_calibrator(self.calibrator)
        check(
            read("thresholds.json") == THRESHOLDS,
            "Probability thresholds differ from frozen contract",
        )
        self.dictionary = read("dictionary.json")
        check(
            self.dictionary.get("extractor") == FEATURE_VERSION
            and set(self.dictionary.get("features", {})) == set(FEATURE_NAMES),
            "RU dictionary feature allowlist mismatch",
        )
        check(
            all(
                isinstance(v.get("title"), str)
                and v["title"].strip()
                and isinstance(v.get("description"), str)
                and v["description"].strip()
                for v in self.dictionary["features"].values()
            ),
            "Incomplete RU dictionary",
        )
        self.protocol = read("protocol.json")
        check(
            self.protocol.get("version") == "aml-labels-v1"
            and self.protocol.get("population_id") == "aml-game-balanced-v1"
            and self.protocol.get("confirmed_class_prior") == 0.5,
            "Invalid probability population/protocol",
        )
        check(
            manifest.get("population_id") == self.protocol["population_id"]
            and manifest.get("label_protocol_version") == self.protocol["version"],
            "Manifest probability population/protocol mismatch",
        )
        check(
            manifest.get("financial_rules_sha256")
            == canonical_hash(fixed_financial_contract()),
            "Package financial rules signature mismatch",
        )
        profiles = manifest.get("allowed_profiles")
        check(
            isinstance(profiles, list)
            and bool(profiles)
            and len(set(profiles)) == len(profiles)
            and all(isinstance(p, str) and p for p in profiles),
            "Invalid profile allowlist",
        )
        categories = manifest.get("category_allowlist")
        check(
            isinstance(categories, dict)
            and set(categories) == set(CATEGORICAL_FEATURES),
            "Invalid categorical allowlist",
        )
        check(
            all(
                isinstance(v, list)
                and bool(v)
                and len(set(v)) == len(v)
                and all(isinstance(s, str) and s for s in v)
                for v in categories.values()
            ),
            "Invalid categorical values",
        )
        channels = manifest.get("allowed_channels")
        if ready or channels is not None:
            check(
                isinstance(channels, list)
                and bool(channels)
                and all(isinstance(v, str) and v for v in channels)
                and len(set(channels)) == len(channels),
                "Invalid channel allowlist",
            )
        evaluation = read("evaluation.json")
        if ready:
            validate_release_artifacts(manifest, read)
            gates = evaluation.get("gates", {})
            check(
                set(gates) == RELEASE_GATES
                and all(v is True for v in gates.values())
                and evaluation.get("release_ready") is True
                and evaluation.get("evaluated_split") == "test",
                "Package release evaluation failed",
            )
            check(
                evaluation.get("model_sha256") == hashes["model.cbm"]
                and evaluation.get("calibration_sha256") == hashes["calibration.json"]
                and evaluation.get("dataset_manifest_sha256")
                == manifest.get("dataset_manifest_sha256")
                and bool(manifest.get("dataset_manifest_sha256")),
                "Release evaluation binding mismatch",
            )
        self.classifier = CatBoostClassifier()
        self.classifier.load_model(str(package / "model.cbm"))
        check(
            self.classifier.classes_.tolist() == [0, 1],
            "Model classes must be exactly ordered binary 0 and 1",
        )
        check(
            self.classifier.feature_names_ == list(FEATURE_NAMES),
            "Model feature names/order mismatch",
        )
        check(
            self.classifier.get_cat_feature_indices()
            == [FEATURE_NAMES.index(n) for n in CATEGORICAL_FEATURES],
            "Model categorical feature mapping mismatch",
        )
        self.model_identity = {
            "package_sha256": sha256((package / "manifest.json").read_bytes()),
            "model_sha256": hashes["model.cbm"],
            "calibration_sha256": hashes["calibration.json"],
            "schema_sha256": hashes["feature-schema.json"],
            "thresholds_sha256": hashes["thresholds.json"],
            "contract_version": 10,
            "extractor_version": FEATURE_VERSION,
        }

    def check_config(self, config):
        check(
            config.get("schema_version") == 10, "Probability model requires v10 config"
        )
        AMLGameConfigOut.model_validate(
            {"config_version": canonical_hash(config), **config}
        )
        validate_config(config)
        check(
            canonical_hash(financial_projection(config))
            == self.manifest["financial_rules_sha256"],
            "Incompatible financial rules",
        )
        check(
            config["behavior"]["profile"]["id"] in self.manifest["allowed_profiles"],
            "Unsupported profile",
        )

    def feature_vector(self, steps, config):
        self.check_config(config)
        if "allowed_channels" in self.manifest:
            channels = {
                s.get("action_details", {}).get("incoming_kind", s["card"]["code"])
                for s in steps
            }
            check(
                channels <= set(self.manifest["allowed_channels"]),
                "Unsupported channel",
            )
        features = extract_features(steps, config)
        check(list(features) == list(FEATURE_NAMES), "Extractor feature order mismatch")
        for name, value in features.items():
            if name in CATEGORICAL_FEATURES:
                check(
                    isinstance(value, str)
                    and value in self.manifest["category_allowlist"][name],
                    f"Unsupported categorical value: {name}",
                )
            else:
                check(
                    type(value) in (int, float) and math.isfinite(value),
                    f"Nonfinite numeric feature: {name}",
                )
        return features

    def predict(self, steps: list, config: dict) -> dict:
        features = self.feature_vector(steps, config)
        pool = Pool(
            [[features[name] for name in FEATURE_NAMES]],
            feature_names=FEATURE_NAMES,
            cat_features=[FEATURE_NAMES.index(n) for n in CATEGORICAL_FEATURES],
        )
        margin = float(
            np.asarray(
                self.classifier.predict(pool, prediction_type="RawFormulaVal")
            ).reshape(-1)[0]
        )
        check(math.isfinite(margin), "Nonfinite raw model margin")
        raw = float(apply_calibrator([margin], {"method": "none"})[0])
        probabilities = np.asarray(self.classifier.predict_proba(pool), dtype=float)
        check(
            probabilities.shape == (1, 2)
            and np.isfinite(probabilities).all()
            and (probabilities >= 0).all()
            and (probabilities <= 1).all()
            and abs(float(probabilities.sum()) - 1) <= 1e-8
            and abs(raw - probabilities[0, 1]) <= 1e-8,
            "Raw sigmoid disagrees with positive class probability",
        )
        shap = np.asarray(
            self.classifier.get_feature_importance(pool, type="ShapValues"), dtype=float
        )
        check(
            shap.shape == (1, len(FEATURE_NAMES) + 1) and np.isfinite(shap).all(),
            "Invalid binary SHAP decomposition",
        )
        base = float(shap[0, -1])
        residual = abs(base + float(shap[0, :-1].sum()) - margin)
        check(residual <= 1e-6, "SHAP reconstruction residual exceeds tolerance")
        probability = float(apply_calibrator([margin], self.calibrator)[0])
        check(
            math.isfinite(probability) and 0 <= probability <= 1,
            "Invalid calibrated probability",
        )
        context = config["behavior"]["aml_context"]
        expected = context["expected_activity"]
        complete = (
            context["history_coverage"] == "complete"
            and all(
                expected.get(f"expected_{direction}_{edge}") is not None
                for direction in ("credit", "debit")
                for edge in ("min", "max")
            )
            and bool(context["opening_balance_facts"])
            and all(
                step.get("purpose_code") not in (None, "unknown")
                and step.get("claim_id")
                for step in steps
            )
        )
        result = dict(
            schema_version=4,
            score_kind="aml_probability",
            aml_probability=probability,
            uncalibrated_probability=raw,
            raw_margin=margin,
            risk_score=100 * probability,
            category=probability_category(probability),
            context_status="complete" if complete else "partial",
            context_sha256=canonical_hash(config["behavior"]),
            model_identity=dict(self.model_identity),
            explanation_space="raw_margin",
            base_margin=base,
            shap_residual=residual,
            shap_values=[
                dict(
                    feature=n,
                    value=features[n],
                    contribution=float(shap[0, i]),
                    title=self.dictionary["features"][n]["title"],
                    description=self.dictionary["features"][n]["description"],
                )
                for i, n in enumerate(FEATURE_NAMES)
            ],
            calibration=dict(
                parameters=self.calibrator,
                input_space="raw_margin",
                output_space="probability",
            ),
        )
        if self.calibrator["method"] == "sigmoid":
            result["calibration"]["calibrated_logit"] = (
                self.calibrator["a"] * margin + self.calibrator["b"]
            )
        return result
