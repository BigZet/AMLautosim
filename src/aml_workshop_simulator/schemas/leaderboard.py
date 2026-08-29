from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BaseResultOut(BaseModel):
    risk_score: str
    risk_label: str
    stealth_score: str
    resource_score: str
    game_score: str


class LeaderboardMetaOut(BaseModel):
    effective_game_score: str
    rank: int
    is_adjusted: bool = False


class ResultOut(BaseModel):
    scenario_id: int
    base: BaseResultOut
    leaderboard: LeaderboardMetaOut
    versions: dict[str, str] = Field(default_factory=dict)
    explanation: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)


class LeaderboardRowOut(BaseModel):
    """Anonymised public row.

    Deliberately carries no email, user id, scenario id, chain or factors —
    and, unless the caller explicitly asked to reveal them, no nickname either.
    """

    rank: int
    #: Masked placeholder (`Игрок #1`) unless the caller asked to reveal names.
    display_name: str
    masked: bool = True
    game_score: str
    stealth_score: str
    resource_score: str
    risk_label: str
    is_adjusted: bool = False
    is_current_user: bool = False


class LeaderboardPageOut(BaseModel):
    rows: list[LeaderboardRowOut]
    next_cursor: str | None = None
    generated_at: datetime
    revealed: bool = False


class AdminLeaderboardRowOut(BaseModel):
    rank: int
    participant_id: int
    display_name: str
    email: str
    scenario_id: int
    is_blocked: bool
    base_game_score: str
    effective_game_score: str
    base_risk_score: str
    effective_risk_score: str
    base_resource_score: str
    effective_resource_score: str
    stealth_score: str
    risk_label: str
    is_adjusted: bool = False
    adjustment_reason: str | None = None


class AdminLeaderboardPageOut(BaseModel):
    rows: list[AdminLeaderboardRowOut]
    next_cursor: str | None = None
    generated_at: datetime
