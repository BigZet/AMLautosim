"""Opt-in inference adapter. Importing the game never loads CatBoost or a model."""

import hashlib
import json
import math
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import (
    FEATURE_VERSION,
    extract_features,
)


def file_sha(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def contract_signature(config):
    """Financial rules and supported contract, excluding observed context and IDs."""
    behavior = config.get("behavior", {})
    cards = []
    keys = (
        "code",
        "version",
        "category",
        "flow",
        "energy_cost",
        "time_cost",
        "fee_rate",
        "min_amount",
        "max_amount",
        "max_occurrences",
        "requires_card_code",
        "quota_category",
        "channels",
        "context_fields",
        "fields",
    )
    for card in config.get("card_snapshots", []):
        canonical = deepcopy({key: card[key] for key in keys})
        # JSON exports materialize these catalog defaults; raw fixtures may omit them.
        for field in canonical["fields"] + canonical["context_fields"]:
            field.setdefault("required", True)
            for option in field.get("options", []):
                for key in ("risk_points", "time_cost", "energy_cost"):
                    option.setdefault(key, 0)
        cards.append(canonical)
    payload = {
        key: config.get(key)
        for key in (
            "schema_version",
            "resources",
            "objectives",
            "constraints",
            "resource_rules",
        )
    }
    payload.update(
        cards=sorted(cards, key=lambda c: c["code"]),
        release=behavior.get("release"),
        sender_policy=behavior.get("sender_policy"),
        purchases=behavior.get("purchases"),
        waiting_costs=behavior.get("timeline", {}).get("waiting_costs"),
    )

    def normalize(value):
        if isinstance(value, dict):
            return {
                k: normalize(v)
                for k, v in value.items()
                if k not in ("label", "help", "description", "title")
            }
        if isinstance(value, list):
            return [normalize(v) for v in value]
        if value is None or isinstance(value, bool):
            return value
        try:
            number = Decimal(str(value))
            if number.is_finite():
                return format(number.normalize(), "f")
        except InvalidOperation:
            pass
        return value

    return hashlib.sha256(
        json.dumps(
            normalize(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class AMLRiskModel:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = json.loads((directory / "manifest.json").read_text())
        if (
            not self.manifest.get("ready_for_integration")
            or self.manifest.get("extractor") != FEATURE_VERSION
        ):
            raise ValueError("Model package is not approved for this extractor")
        for name in (
            "aml_risk_model.py",
            "aml_dataset_features_v3.py",
            "aml_dataset_features_v2.py",
            "aml_episodes.py",
        ):
            if file_sha(Path(__file__).parent / name) != self.manifest.get(
                "source_checksums", {}
            ).get(name):
                raise ValueError(f"Inference source version mismatch: {name}")
        for name in ("model.cbm", "feature-schema.json"):
            if file_sha(directory / name) != self.manifest["checksums"][name]:
                raise ValueError(f"Model package checksum mismatch: {name}")
        self.schema = json.loads((directory / "feature-schema.json").read_text())
        if self.schema["version"] != FEATURE_VERSION:
            raise ValueError("Feature version mismatch")
        self.columns = self.schema["columns"]
        if len(self.columns) != len(set(self.columns)) or any(
            k in self.columns
            for k in (
                "target_risk_score",
                "risk_score",
                "game_score",
                "id",
                "group",
                "seed",
                "baseline",
            )
        ):
            raise ValueError("Invalid model feature schema")
        from catboost import CatBoostRegressor

        self.model = CatBoostRegressor()
        self.model.load_model(str(directory / "model.cbm"))
        if self.model.feature_names_ != self.columns:
            raise ValueError("Model and schema feature names differ")

    def predict_features(self, features):
        """Internal feature contract, with explicit name alignment and validation."""
        missing = set(self.columns) - features.keys()
        if missing:
            raise ValueError(f"Missing model features: {sorted(missing)}")
        values = []
        for key in self.columns:
            value = features[key]
            if key in self.schema["categorical"]:
                if not isinstance(value, str) or not value:
                    raise ValueError(f"Invalid categorical feature: {key}")
            else:
                try:
                    value = float(value)
                except (ValueError, TypeError) as error:
                    raise ValueError(f"Invalid numeric feature: {key}") from error
                if not math.isfinite(value):
                    raise ValueError(f"Nonfinite feature: {key}")
            values.append(value)
        from catboost import Pool

        prediction = float(
            self.model.predict(
                Pool(
                    [values],
                    feature_names=self.columns,
                    cat_features=self.schema["categorical"],
                ),
                thread_count=1,
            )[0]
        )
        if not math.isfinite(prediction):
            raise ValueError("Nonfinite model prediction")
        return min(100.0, max(0.0, prediction))

    def predict(self, steps, config):
        if (
            config.get("schema_version") != 8
            or contract_signature(config) != self.manifest["game_contract_signature"]
        ):
            raise ValueError("This model does not support the round financial contract")
        blockers = submit_blockers(evaluate_expanded_scenario(steps, config))
        if blockers:
            raise ValueError("Model supports only valid goal-completing scenarios")
        return self.predict_features(extract_features(steps, config))
