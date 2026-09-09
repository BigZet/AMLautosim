"""Read-only scoring and leaderboard responses."""

from datetime import datetime

from pydantic import BaseModel

from src.aml_workshop_simulator.core.enums import RiskLabel
from src.aml_workshop_simulator.schemas.game_state import ResourceSnapshotOut
from src.aml_workshop_simulator.schemas.scoring import ScoringExplanationOut


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
    explanation: ScoringExplanationOut
    resources: ResourceSnapshotOut


class LeaderboardRowOut(BaseModel):
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


class AdminLeaderboardRowOut(BaseModel):
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
