"""Verified fixed-history classifier; no teaching labels are evaluated online."""

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
import math
import os
from pathlib import Path

from catboost import CatBoostClassifier, CatBoostError, Pool
import numpy as np
import pandas as pd

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services.source_hashing import source_sha256
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
    extract_panel_features,
)
from src.aml_workshop_simulator.services.aml_game_window_model_v2 import (
    FEATURES,
    WINDOWS,
    views,
    calibrated,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGE = ROOT / "resources/catboost_models/aml-game-organizer-settings-v1"
INFERENCE_FILES = (
    "src/aml_workshop_simulator/services/aml_game_pattern_panel.py",
    "src/aml_workshop_simulator/services/aml_game_pattern_panel_v2.py",
    "src/aml_workshop_simulator/services/aml_game_window_model_v2.py",
)
REQUIRED = {
    "model.cbm",
    "manifest.json",
    "context.json",
    "acceptance.json",
    "readback-audit.json",
    "gameplay-audit.json",
    "features.json",
}


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def contract(config):
    from src.aml_workshop_simulator.schemas.round_config import (
        parse_game_config,
        CardSnapshotOut,
    )

    value = parse_game_config(
        {
            k: v
            for k, v in config.items()
            if k not in ("card_snapshots", "config_version", "risk_model")
        }
    ).dump()
    # Database identifiers do not affect the financial/card contract.
    cards = [
        CardSnapshotOut.model_validate(c).model_dump(mode="json", exclude={"id"})
        for c in config.get("card_snapshots", [])
    ]
    value["card_snapshots"] = sorted(cards, key=lambda c: (c["code"], c["version"]))
    return value


class GameClassifier:
    def __init__(self, package):
        self.package = Path(package)
        self.release = json.loads((self.package / "release.json").read_bytes())
        self.extractor_version = self.release.get('extractor_version', 'aml-game-window-v2')
        self.inference_files = INFERENCE_FILES
        self.features, self.extract, self.views = FEATURES, extract_panel_features, views
        if self.extractor_version == 'aml-game-attributes-context-v1':
            from . import aml_game_attribute_features_v1 as contextual
            self.features, self.extract, self.views = contextual.FEATURES, contextual.extract_panel_features, contextual.views
            self.inference_files = (*INFERENCE_FILES, 'src/aml_workshop_simulator/services/aml_game_attribute_features_v1.py')
        elif self.extractor_version != 'aml-game-window-v2':
            raise ValueError('Unsupported classifier extractor')
        if (
            self.release.get("format") != "aml-game-package-v1"
            or set(self.release["files"]) != REQUIRED
        ):
            raise ValueError("Unsupported classifier package")
        self.package_sha256 = digest(self.release)
        self.verify_integrity()
        self.manifest = json.loads((self.package / "manifest.json").read_bytes())
        if self.manifest.get('extractor_version', 'aml-game-window-v2') != self.extractor_version:
            raise ValueError('Extractor contract mismatch')
        acceptance = json.loads((self.package / "acceptance.json").read_bytes())
        replay = json.loads((self.package / "readback-audit.json").read_bytes())
        gameplay = json.loads((self.package / "gameplay-audit.json").read_bytes())
        from src.aml_workshop_simulator.services.classifier_acceptance import gameplay_accepted
        if not (
            acceptance["ready_for_training"]
            and replay["passed"]
            and gameplay_accepted(gameplay, self.release['files']['gameplay-audit.json'], acceptance.get('gameplay_exception'))
            and self.manifest["offline_quality_passed"]
            and not self.manifest["failures"]
        ):
            raise ValueError("Classifier acceptance failed")
        if (
            acceptance["model_manifest_sha256"]
            != self.release["files"]["manifest.json"]
            or acceptance["readback_sha256"]
            != self.release["files"]["readback-audit.json"]
            or acceptance["gameplay_audit_sha256"]
            != self.release["files"]["gameplay-audit.json"]
            or self.manifest["model_sha256"] != self.release["files"]["model.cbm"]
        ):
            raise ValueError("Acceptance does not bind this model")
        self.context = json.loads((self.package / "context.json").read_bytes())
        self.dictionary = json.loads((self.package / "features.json").read_bytes())
        if (
            self.manifest["architecture"] != "mean_of_three_shared_classifier_views"
            or self.manifest["features"] != self.features
            or self.dictionary["features"] != self.features
            or set(self.dictionary["titles"]) != set(self.features)
            or self.manifest["dataset_hashes"]["context.json"]
            != self.release["files"]["context.json"]
        ):
            raise ValueError("Feature or context contract mismatch")
        calibration = self.manifest["calibration"]
        if calibration.get("method") not in ("none", "sigmoid") or (
            calibration["method"] == "sigmoid"
            and not all(math.isfinite(calibration[k]) for k in ("a", "b"))
        ):
            raise ValueError("Unsupported calibration")
        self.model = CatBoostClassifier()
        self.model.load_model(str(self.package / "model.cbm"))
        if self.model.feature_names_ != self.features or list(self.model.classes_) != [0, 1]:
            raise ValueError("Model input/class order mismatch")
        self.expected_contract = contract(self.context)
        self.context_sha256 = digest(self.expected_contract)
        self.model_identity = dict(
            package_sha256=self.package_sha256,
            model_sha256=self.manifest["model_sha256"],
            context_sha256=self.context_sha256,
            feature_schema_sha256=self.release["files"]["features.json"],
            contract_version=10,
            extractor_version=self.extractor_version,
        )
        self.identity = dict(
            self.model_identity,
            score_kind="educational_pattern_probability",
            model_version="aml-game:sha256:" + self.package_sha256,
            explanation_version=5,
        )

    def verify_integrity(self):
        current = json.loads((self.package / "release.json").read_bytes())
        if current != self.release:
            raise ValueError("Classifier release changed")
        mode = self.release.get("source_hash_mode", "raw-v1")
        if mode not in ("raw-v1", "lf-v1"):
            raise ValueError("Unsupported source hash mode")
        source_hash = source_sha256 if mode == "lf-v1" else file_hash
        for name, expected in self.release["files"].items():
            if file_hash(self.package / name) != expected:
                raise ValueError("Classifier artifact changed: " + name)
        if set(self.release["inference_sources"]) != set(self.inference_files):
            raise ValueError("Incomplete inference source contract")
        for name, expected in self.release["inference_sources"].items():
            if source_hash(ROOT / name) != expected:
                raise ValueError("Classifier feature implementation changed")

        for name, expected in self.release.get("compatibility_sources", {}).items():
            if source_hash(ROOT / name) != expected:
                raise ValueError("Classifier compatibility implementation changed")

    def pin_identity(self, config):
        return deepcopy(self.identity)

    def check_config(self, config, *, require_pin=False):
        try:
            self.verify_integrity()
        except (OSError, ValueError, KeyError) as exc:
            raise Conflict(
                "Пакет классификатора недоступен или изменён.", code="model_unavailable"
            ) from exc
        actual = contract(config)
        expected = deepcopy(self.expected_contract)
        if self.release.get("organizer_settings_version") == 1:
            # Round settings are frozen separately; the model vocabulary stays fixed.
            for key in ("resources", "objectives", "constraints"):
                actual[key] = expected[key]
            for key in ("profile", "history", "purchases"):
                actual["behavior"][key] = expected["behavior"][key]
            for key in ("history_coverage", "history_start", "history_end"):
                actual["behavior"]["aml_context"][key] = expected["behavior"]["aml_context"][key]
            for operation in actual["operations"]:
                reference = next((o for o in expected["operations"] if (o["code"], o["version"]) == (operation["code"], operation["version"])), {})
                for key in ("min_amount", "max_amount", "max_occurrences"):
                    if key in reference:
                        operation[key] = reference[key]
                    else:
                        operation.pop(key, None)
        if actual != expected:
            raise Conflict(
                "Изменены параметры, не совместимые с контрактом классификатора.",
                code="model_contract_mismatch",
            )
        accepted_pins = [self.identity, *self.release.get("compatible_identities", [])]
        if require_pin and config.get("risk_model") not in accepted_pins:
            raise Conflict(
                "Закреплённый пакет классификатора изменён.",
                code="model_version_mismatch",
            )

    def predict(self, steps, config, *, explain=True, require_pin=True):
        self.check_config(config, require_pin=require_pin)
        from src.aml_workshop_simulator.services.aml_context import canonical_steps

        steps = canonical_steps(steps, config)
        features = self.extract(steps)
        frame = self.views(pd.DataFrame([features]))[self.features]
        pool = Pool(frame, feature_names=self.features)
        probabilities = self.model.predict_proba(pool, thread_count=1)[:, 1]
        mean = float(probabilities.mean())
        probability = float(
            calibrated(np.array([mean]), self.manifest["calibration"])[0]
        )
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Invalid classifier probability")
        if not explain:
            return probability
        margins = np.asarray(
            self.model.predict(pool, prediction_type="RawFormulaVal", thread_count=1)
        )
        shap = np.asarray(
            self.model.get_feature_importance(pool, type="ShapValues", thread_count=1)
        )
        windows = []
        for i, window in enumerate(WINDOWS):
            residual = abs(float(shap[i].sum()) - float(margins[i]))
            if residual > 1e-6 or not np.isfinite(shap[i]).all():
                raise ValueError("Invalid window SHAP decomposition")
            windows.append(
                dict(
                    minutes=window,
                    probability=float(probabilities[i]),
                    raw_margin=float(margins[i]),
                    base_margin=float(shap[i, -1]),
                    shap_residual=residual,
                    shap_values=[
                        dict(
                            feature=name,
                            value=float(frame.iloc[i][name]),
                            contribution=float(shap[i, j]),
                            title=self.dictionary["titles"][name],
                            description=self.dictionary["descriptions"][name],
                        )
                        for j, name in enumerate(self.features)
                    ],
                )
            )
        return dict(
            schema_version=5,
            score_kind="educational_pattern_probability",
            aml_probability=probability,
            uncalibrated_probability=mean,
            risk_score=100 * probability,
            category="low"
            if probability < 0.1
            else "high"
            if probability >= 0.9
            else "review",
            context_sha256=self.context_sha256,
            model_identity=self.model_identity,
            windows=windows,
            calibration=dict(
                parameters=self.manifest["calibration"],
                input_space="logit_mean_probability",
                output_space="probability",
            ),
        )

    def score(self, steps, config, *, require_pin=True):
        from src.aml_workshop_simulator.services.model_scoring import rounded
        from src.aml_workshop_simulator.schemas.scoring import GamePatternExplanationOut

        explanation = self.predict(steps, config, require_pin=require_pin)
        GamePatternExplanationOut.model_validate(explanation)
        return dict(
            risk_score=rounded(explanation["risk_score"]),
            risk_label={"low": "normal", "review": "review", "high": "suspicious"}[
                explanation["category"]
            ],
            explanation=explanation,
        )


@lru_cache(maxsize=4)
def _load(package):
    return GameClassifier(package)


def get_game_classifier():
    from src.aml_workshop_simulator.core.config import project_path

    path = project_path(
        os.environ.get("AML_PROBABILITY_MODEL_PATH", str(DEFAULT_PACKAGE))
    )
    try:
        model = _load(str(path))
        model.verify_integrity()
        return model
    except (OSError, ValueError, KeyError, CatBoostError) as exc:
        raise Conflict(
            "Проверенный пакет учебного классификатора недоступен.",
            code="model_unavailable",
        ) from exc


def game_config():
    from src.aml_workshop_simulator.schemas.round_config import parse_game_config
    return parse_game_config({
        k: deepcopy(v)
        for k, v in get_game_classifier().context.items()
        if k not in ("card_snapshots", "config_version", "risk_model")
    }).dump()


def get_pinned_game_classifier(config):
    """Keep saved rounds on their exact released package during a gradual rollout."""
    current = get_game_classifier()
    pin = config.get("risk_model")
    if not pin or pin == current.identity or pin in current.release.get("compatible_identities", []):
        return current
    # Server-owned registry only; client pins never select filesystem locations.
    from src.aml_workshop_simulator.services.model_registry import classifier_paths

    for path in classifier_paths():
        release = path / "release.json"
        if not release.is_file():
            continue
        try:
            if digest(json.loads(release.read_bytes())) != pin.get("package_sha256"):
                continue
            model = _load(str(path.resolve()))
            model.check_config(config, require_pin=True)
            return model
        except (OSError, ValueError, KeyError, CatBoostError) as exc:
            raise Conflict("Закреплённый пакет классификатора недоступен.", code="model_unavailable") from exc
    raise Conflict("Закреплённый пакет классификатора не найден.", code="model_version_mismatch")
