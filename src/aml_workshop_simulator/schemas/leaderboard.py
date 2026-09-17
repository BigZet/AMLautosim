"""Read-only scoring and leaderboard responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.aml_workshop_simulator.core.enums import RiskLabel
from src.aml_workshop_simulator.schemas.game_state import ResourceSnapshotOut
from src.aml_workshop_simulator.schemas.scoring import PublishedScoringExplanationOut


class BaseResultOut(BaseModel):
    risk_score: str
    risk_label: RiskLabel
    stealth_score: str
    resource_score: str
    game_score: str


class ResultOut(BaseModel):
    scenario_id: int
    scores: BaseResultOut
    rank: int | None = None
    explanation: PublishedScoringExplanationOut
    resources: ResourceSnapshotOut


class LeaderboardSemanticsOut(BaseModel):
    score_kind: Literal[
        "legacy_risk", "aml_probability", "educational_pattern_probability"
    ] = "legacy_risk"
    leaderboard_version: Literal["leaderboard-v2", "leaderboard-aml-probability-v1"] = (
        "leaderboard-v2"
    )
    aml_probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    category: Literal["low", "review", "high"] | None = None

    @model_validator(mode="after")
    def coherent_semantics(self):
        if self.score_kind in ("aml_probability", "educational_pattern_probability"):
            p = self.aml_probability
            if (
                p is None
                or self.leaderboard_version != "leaderboard-aml-probability-v1"
            ):
                raise ValueError(
                    "Probability leaderboard requires probability and version"
                )
            expected = "low" if p < 0.1 else "high" if p >= 0.9 else "review"
            if self.category != expected:
                raise ValueError(
                    "Probability category must match unrounded probability"
                )
        elif (
            self.aml_probability is not None
            or self.category is not None
            or self.leaderboard_version != "leaderboard-v2"
        ):
            raise ValueError("Legacy leaderboard cannot carry probability semantics")
        return self


class LeaderboardRowOut(LeaderboardSemanticsOut):
    rank: int
    display_name: str
    game_score: str
    stealth_score: str
    resource_score: str
    risk_label: RiskLabel
    is_current_user: bool = False


class LeaderboardPageOut(BaseModel):
    rows: list[LeaderboardRowOut]
    generated_at: datetime


class AdminLeaderboardRowOut(LeaderboardSemanticsOut):
    rank: int | None
    participant_id: int
    display_name: str
    email: str
    scenario_id: int
    is_blocked: bool
    game_score: str
    risk_score: str
    resource_score: str
    stealth_score: str
    risk_label: RiskLabel


class AdminLeaderboardPageOut(BaseModel):
    rows: list[AdminLeaderboardRowOut]
    generated_at: datetime
