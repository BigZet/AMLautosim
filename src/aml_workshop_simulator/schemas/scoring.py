"""Published contract of the temporary rule-based scorer."""

from pydantic import BaseModel, JsonValue


class ScoringFactorOut(BaseModel):
    step_id: str | None
    code: str
    category: str
    points: str
    description: str
    evidence: dict[str, JsonValue]


class RiskThresholdsOut(BaseModel):
    review: str
    suspicious: str


class ScoringExplanationOut(BaseModel):
    schema_version: int
    scoring_version: str
    top_risk_factors: list[ScoringFactorOut]
    protective_factors: list[ScoringFactorOut]
    sequence_factors: list[ScoringFactorOut]
    all_factors: list[ScoringFactorOut]
    raw_score: str
    normalized_score: str
    step_count: int
    thresholds: RiskThresholdsOut
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
