"""The sole online risk scorer: pinned CatBoost prediction and local Tree SHAP."""

import json
from copy import deepcopy
import math
import os
from decimal import Decimal, ROUND_HALF_EVEN
from functools import lru_cache
from pathlib import Path

from catboost import Pool

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.core.config import project_path
from src.aml_workshop_simulator.services.aml_risk_model import (
    AMLRiskModel,
    contract_signature,
    file_sha,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import extract_features

EXPLANATION_VERSION = 3
PACKAGE = project_path(
    os.environ.get("AML_MODEL_PATH", "resources/catboost_models/integration-v2-final")
)
DICTIONARY = project_path("config/model/feature-descriptions.json")


def rounded(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


class LegacyOnlineModel(AMLRiskModel):
    """Apply retired-rule compatibility without changing the archived extractor."""

    def check_contract(self, config):
        # Retired limits are irrelevant to inference, but remain in the archived
        # v8 signature. Project only those keys to its frozen reference values.
        signature_config = deepcopy(config)
        frozen = json.loads(project_path("config/model/smoke-scenario.json").read_bytes())["config"]["constraints"]
        constraints = signature_config["constraints"]
        for key in ("max_night_operations", "max_anonymous_operations"):
            constraints[key] = frozen[key]
        constraints.setdefault("category_limits", {})["anonymous"] = frozen["category_limits"]["anonymous"]
        if (config.get("schema_version") != 8
                or contract_signature(signature_config) != self.manifest["game_contract_signature"]):
            raise Conflict("Конфигурация не поддерживается моделью CatBoost.",
                           code="model_contract_mismatch")

    def predict(self, steps, config):
        from src.aml_workshop_simulator.domain.simulation import submit_blockers
        from src.aml_workshop_simulator.services.expanded_simulation import evaluate_expanded_scenario

        self.check_contract(config)
        if submit_blockers(evaluate_expanded_scenario(steps, config)):
            raise ValueError("Model supports only valid goal-completing scenarios")
        return self.predict_features(extract_features(steps, config))


class ModelScorer:
    def __init__(self):
        self.adapter = LegacyOnlineModel(PACKAGE)
        self.dictionary = json.loads(DICTIONARY.read_text())
        if set(self.dictionary["features"]) != set(self.adapter.columns):
            raise ValueError("Incomplete SHAP feature dictionary")
        self.identity = dict(
            model_version=self.adapter.manifest["model_version"],
            model_sha256=self.adapter.manifest["checksums"]["model.cbm"],
            extractor=self.adapter.manifest["extractor"],
            explanation_version=EXPLANATION_VERSION,
            dictionary_sha256=file_sha(DICTIONARY),
        )
        # A packaged, valid scenario checks both feature extraction and native SHAP.
        smoke = json.loads(project_path("config/model/smoke-scenario.json").read_bytes())
        self.check_config(smoke["config"])
        self.score(smoke["steps"], smoke["config"], require_pin=False)

    def check_config(self, config, *, require_pin=False):
        self.adapter.check_contract(config)
        cards = {c["code"]: c for c in config["card_snapshots"]}
        if {o["code"] for o in config["operations"]} != set(cards):
            raise Conflict(
                "Набор операций не поддерживается моделью.",
                code="model_contract_mismatch",
            )
        # Overrides are not included in the original model signature. Guard them here.
        from src.aml_workshop_simulator.domain.round_policy import CARD_OVERRIDE_KEYS

        for operation in config["operations"]:
            for key in CARD_OVERRIDE_KEYS:
                value = operation.get(key)
                expected = cards[operation["code"]].get(key)
                if value is not None and str(value) != str(expected):
                    try:
                        same = Decimal(str(value)) == Decimal(str(expected))
                    except Exception:
                        same = value == expected
                    if not same:
                        raise Conflict(
                            "Изменение затрат или лимитов не поддерживается моделью.",
                            code="model_contract_mismatch",
                        )
        if require_pin and config.get("risk_model") != self.identity:
            raise Conflict(
                "Закреплённая модель или версия объяснений недоступна.",
                code="model_version_mismatch",
            )

    def score(self, steps, config, *, require_pin=True):
        self.check_config(config, require_pin=require_pin)
        prediction = self.adapter.predict(steps, config)
        features = extract_features(steps, config)
        pool = Pool(
            [[features[k] for k in self.adapter.columns]],
            feature_names=self.adapter.columns,
            cat_features=self.adapter.schema["categorical"],
        )
        raw = float(self.adapter.model.predict(pool, thread_count=1)[0])
        shap = self.adapter.model.get_feature_importance(
            pool, type="ShapValues", thread_count=1
        )[0]
        if (
            len(shap) != len(self.adapter.columns) + 1
            or not all(math.isfinite(float(v)) for v in shap)
            or not math.isfinite(raw)
        ):
            raise ValueError("Invalid SHAP output")
        residual = abs(float(sum(shap)) - raw)
        if residual > 1e-6 or abs(prediction - min(100, max(0, raw))) > 1e-8:
            raise ValueError("SHAP additivity check failed")
        score = rounded(prediction)
        factors = []
        for key, contribution in zip(self.adapter.columns, shap[:-1]):
            entry = self.dictionary["features"][key]
            value = features[key]
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError("Nonfinite feature")
            formatted = format_value(value, entry["format"])
            factors.append(
                dict(
                    code=key,
                    title=entry["title"],
                    description=entry["description"],
                    unit=entry["unit"],
                    value=value,
                    display_value=formatted,
                    contribution=float(contribution),
                )
            )
        positive = sorted(
            [f for f in factors if f["contribution"] >= 0.005],
            key=lambda f: (-f["contribution"], f["code"]),
        )[:3]
        negative = sorted(
            [f for f in factors if f["contribution"] <= -0.005],
            key=lambda f: (f["contribution"], f["code"]),
        )[:3]
        selected = {f["code"] for f in positive + negative}
        thresholds = config["scoring"]
        label = (
            "suspicious"
            if score >= Decimal(str(thresholds["suspicious_threshold"]))
            else "review"
            if score >= Decimal(str(thresholds["review_threshold"]))
            else "normal"
        )
        explanation = dict(
            schema_version=EXPLANATION_VERSION,
            method="catboost-tree-shap",
            model=self.identity,
            reference="training leaf statistics; no reference_data",
            base_value=float(shap[-1]),
            raw_score=raw,
            normalized_score=str(score),
            clipping_adjustment=prediction - raw,
            rounding_adjustment=float(score) - prediction,
            additivity_error=residual,
            factors=factors,
            top_positive=[f["code"] for f in positive],
            top_negative=[f["code"] for f in negative],
            remaining_contribution=sum(
                f["contribution"] for f in factors if f["code"] not in selected
            ),
            disclaimer="Вклады объясняют оценку модели относительно её базового значения; это не фиксированные штрафы и скидки.",
        )
        return dict(risk_score=score, risk_label=label, explanation=explanation)


def format_value(value, kind):
    if kind == "category":
        return {
            "absent": "Дохода нет",
            "payroll_registry": "Зарплатный реестр",
            "service_contract": "Договор услуг",
            "no_reference": "Без назначения",
        }.get(value, str(value))
    if kind == "boolean":
        return "Да" if value else "Нет"
    if kind == "percent":
        return f"{value * 100:.2f}%"
    if kind == "integer":
        return str(int(value))
    return f"{value:.2f}"


@lru_cache(maxsize=1)
def get_model_scorer():
    return ModelScorer()


class ProbabilityScorer:
    """Online v10 adapter: only a release-validated package can be loaded."""

    def __init__(self, package):
        from src.aml_workshop_simulator.services.aml_probability_model import (
            AMLProbabilityModel,
        )

        self.adapter = AMLProbabilityModel(Path(package))
        self._model_identity = dict(self.adapter.model_identity)
        self._identity = dict(
            self._model_identity,
            score_kind="aml_probability",
            model_version="aml-probability:sha256:"
            + self.adapter.model_identity["package_sha256"],
            explanation_version=4,
        )

    @property
    def identity(self):
        return self._identity.copy()

    def pin_identity(self, config):
        from src.aml_workshop_simulator.services.aml_probability_model import (
            canonical_hash,
        )

        return dict(self.identity, context_sha256=canonical_hash(config["behavior"]))

    def check_config(self, config, *, require_pin=False):
        try:
            self.adapter.check_config(config)
        except ValueError as exc:
            raise Conflict(
                "Конфигурация не поддерживается AML-классификатором.",
                code="model_contract_mismatch",
            ) from exc
        if require_pin and config.get("risk_model") != self.pin_identity(config):
            raise Conflict(
                "Закреплённый пакет или контекст AML-классификатора недоступен.",
                code="model_version_mismatch",
            )

    def score(self, steps, config, *, require_pin=True):
        from src.aml_workshop_simulator.schemas.scoring import (
            AMLProbabilityExplanationOut,
        )

        self.check_config(config, require_pin=require_pin)
        explanation = self.adapter.predict(steps, config)
        AMLProbabilityExplanationOut.model_validate(explanation)
        if (
            explanation["model_identity"] != self._model_identity
            or explanation["context_sha256"]
            != self.pin_identity(config)["context_sha256"]
        ):
            raise Conflict(
                "Изменился пакет или контекст результата.",
                code="model_version_mismatch",
            )
        probability = explanation["aml_probability"]
        return dict(
            risk_score=rounded(Decimal(str(probability)) * 100),
            risk_label={"low": "normal", "review": "review", "high": "suspicious"}[
                explanation["category"]
            ],
            explanation=explanation,
        )


@lru_cache(maxsize=4)
def _probability_scorer(package):
    return ProbabilityScorer(package)


def get_round_scorer(config):
    """Only the current v10 contract is supported; unavailable pins never fall back."""
    version = config.get("schema_version")
    if type(version) is int and version == 10:
        from src.aml_workshop_simulator.services.game_classifier import (
            get_pinned_game_classifier,
        )

        return get_pinned_game_classifier(config)

    raise Conflict(
        "Контракт не поддерживается моделью.", code="model_contract_mismatch"
    )
