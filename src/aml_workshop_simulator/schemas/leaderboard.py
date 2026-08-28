from __future__ import annotations

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


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
    versions: dict[str, str] = {}
    explanation: dict[str, Any] = {}


class LeaderboardRowOut(BaseModel):
    rank: int
    display_name: str
    game_score: str
    stealth_score: str
    resource_score: str
    risk_score: str
    risk_label: str
    is_adjusted: bool = False
    is_current_user: bool = False
    balance: Optional[str] = None
    energy: Optional[int] = None
    time: Optional[int] = None
    trust: Optional[int] = None
    fees: Optional[str] = None


class LeaderboardPageOut(BaseModel):
    rows: list[LeaderboardRowOut]
    next_cursor: Optional[str] = None
    generated_at: datetime
