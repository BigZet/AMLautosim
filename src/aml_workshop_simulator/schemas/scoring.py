"""Published CatBoost and SHAP result contract."""

from math import isclose
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class ShapFactorOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    code: str
    title: str
    description: str
    unit: str
    value: JsonValue
    display_value: str
    contribution: float


class ScoringExplanationOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    schema_version: Literal[3]
    method: Literal["catboost-tree-shap"]
    model: dict[str, JsonValue]
    reference: str
    base_value: float
    raw_score: float
    normalized_score: str
    clipping_adjustment: float
    rounding_adjustment: float
    additivity_error: float
    factors: list[ShapFactorOut]
    top_positive: list[str]
    top_negative: list[str]
    remaining_contribution: float
    disclaimer: str


class AMLShapFactorOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    feature: str
    value: float | str
    contribution: float
    title: str
    description: str


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AMLModelIdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_sha256: Sha256
    model_sha256: Sha256
    calibration_sha256: Sha256
    schema_sha256: Sha256
    thresholds_sha256: Sha256
    contract_version: Literal[10]
    extractor_version: Literal["aml-observable-v5.0"]


class AMLCalibrationOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    parameters: dict[str, JsonValue]
    input_space: Literal["raw_margin"]
    output_space: Literal["probability"]
    calibrated_logit: float | None = None

    @field_validator("parameters")
    @classmethod
    def check_method(cls, value):
        if value.get("method") not in ("none", "sigmoid", "isotonic"):
            raise ValueError("Unsupported calibration method")
        return value


class AMLProbabilityExplanationOut(BaseModel):
    """Stored v4 runtime output; probability is never rounded in this DTO."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    schema_version: Literal[4]
    score_kind: Literal["aml_probability"]
    aml_probability: float = Field(ge=0, le=1)
    uncalibrated_probability: float = Field(ge=0, le=1)
    raw_margin: float
    risk_score: float = Field(ge=0, le=100)
    category: Literal["low", "review", "high"]
    context_status: Literal["complete", "partial"]
    context_sha256: Sha256
    model_identity: AMLModelIdentityOut
    explanation_space: Literal["raw_margin"]
    base_margin: float
    shap_residual: float = Field(ge=0, le=1e-6)
    shap_values: list[AMLShapFactorOut]
    calibration: AMLCalibrationOut

    @model_validator(mode="after")
    def check_probability_summary(self):
        p = self.aml_probability
        expected_category = "low" if p < 0.1 else "high" if p >= 0.9 else "review"
        if self.category != expected_category:
            raise ValueError("Category must use the unrounded AML probability")
        if not isclose(self.risk_score, 100 * p, rel_tol=0, abs_tol=1e-10):
            raise ValueError("Explanation risk_score must equal 100 * aml_probability")
        return self


class GamePatternIdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_sha256: Sha256
    model_sha256: Sha256
    context_sha256: Sha256
    feature_schema_sha256: Sha256
    contract_version: Literal[10]
    extractor_version: Literal["aml-game-window-v2", "aml-game-attributes-context-v1"]


class GameWindowExplanationOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    minutes: Literal[2, 10, 60]
    probability: float = Field(ge=0, le=1)
    raw_margin: float
    base_margin: float
    shap_residual: float = Field(ge=0, le=1e-6)
    shap_values: list[AMLShapFactorOut]

    @model_validator(mode="after")
    def valid_shap(self):
        from math import exp

        if not isclose(
            self.base_margin + sum(f.contribution for f in self.shap_values),
            self.raw_margin,
            abs_tol=1e-6,
            rel_tol=0,
        ):
            raise ValueError("Window SHAP must reconstruct its margin")
        sigmoid = (
            1 / (1 + exp(-self.raw_margin))
            if self.raw_margin >= 0
            else exp(self.raw_margin) / (1 + exp(self.raw_margin))
        )
        if not isclose(sigmoid, self.probability, abs_tol=1e-10, rel_tol=0):
            raise ValueError("Window probability must match its margin")
        return self


class GameCalibrationOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    parameters: dict[str, JsonValue]
    input_space: Literal["logit_mean_probability"]
    output_space: Literal["probability"]


class GamePatternExplanationOut(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    schema_version: Literal[5]
    score_kind: Literal["educational_pattern_probability"]
    aml_probability: float = Field(ge=0, le=1)
    uncalibrated_probability: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=100)
    category: Literal["low", "review", "high"]
    context_sha256: Sha256
    model_identity: GamePatternIdentityOut
    windows: list[GameWindowExplanationOut]
    calibration: GameCalibrationOut

    @model_validator(mode="after")
    def coherent_prediction(self):
        from math import exp, log, isfinite

        if [w.minutes for w in self.windows] != [2, 10, 60]:
            raise ValueError("Three ordered time windows are required")
        mean = sum(w.probability for w in self.windows) / 3
        p = self.aml_probability
        if not isclose(mean, self.uncalibrated_probability, abs_tol=1e-10, rel_tol=0):
            raise ValueError("Window mean mismatch")
        parameters = self.calibration.parameters
        if parameters.get("method") == "none":
            expected = mean
        elif parameters.get("method") == "sigmoid":
            a, b = parameters.get("a"), parameters.get("b")
            if (
                type(a) not in (float, int)
                or type(b) not in (float, int)
                or not isfinite(a)
                or not isfinite(b)
            ):
                raise ValueError("Invalid calibration parameters")
            q = min(max(mean, 1e-12), 1 - 1e-12)
            z = max(-700, min(700, a * log(q / (1 - q)) + b))
            expected = 1 / (1 + exp(-z))
        else:
            raise ValueError("Unknown calibration method")
        category = "low" if p < 0.1 else "high" if p >= 0.9 else "review"
        if (
            not isclose(p, expected, abs_tol=1e-10, rel_tol=0)
            or self.category != category
            or not isclose(self.risk_score, 100 * p, abs_tol=1e-10, rel_tol=0)
        ):
            raise ValueError("Probability summary mismatch")
        if self.context_sha256 != self.model_identity.context_sha256:
            raise ValueError("Context identity mismatch")
        return self


PublishedScoringExplanationOut = Annotated[
    ScoringExplanationOut | AMLProbabilityExplanationOut | GamePatternExplanationOut,
    Field(discriminator="schema_version"),
]


class ScoringCountsOut(BaseModel):
    submitted_count: int
    scored_count: int
    duration_ms: int
    scoring_version: str
    leaderboard_version: str


class ScoringErrorOut(BaseModel):
    code: str
    request_id: str | None
    message: str | None = None
