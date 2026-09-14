"""Published CatBoost and SHAP result contract."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, JsonValue


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


class ScoringCountsOut(BaseModel):
    submitted_count: int
    scored_count: int
    duration_ms: int
    scoring_version: str
    leaderboard_version: str


class ScoringErrorOut(BaseModel):
    code: str
    request_id: str | None
