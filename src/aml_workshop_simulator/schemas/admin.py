from __future__ import annotations

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class RoundCreateIn(BaseModel):
    title: str
    game_config: dict[str, Any]


class RoundUpdateIn(BaseModel):
    expected_config_revision: int
    title: Optional[str] = None
    game_config: Optional[dict[str, Any]] = None


class RoundAdminOut(BaseModel):
    id: int
    title: str
    status: str
    config_revision: int
    game_config: dict[str, Any]
    scoring_summary: Optional[dict[str, Any]] = None
    created_at: datetime
    activated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RoundStatsOut(BaseModel):
    registered_users: int
    active_users: int
    blocked_users: int
    without_scenario: int
    draft_scenarios: int
    submitted_scenarios: int
    scored_scenarios: int
    public_leaderboard_rows: int
    last_scenario_update_at: Optional[datetime] = None


class ScoringSummaryOut(BaseModel):
    round_id: int
    status: str
    submitted_count: int
    scored_count: int
    excluded_draft_count: int
    duration_ms: int
    scoring_version: str
    leaderboard_version: str
    completed_at: datetime


class PlayerSummaryOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    is_blocked: bool
    scenario_status: Optional[str] = None
    game_score: Optional[str] = None
    risk_label: Optional[str] = None
    last_login_at: Optional[datetime] = None


class PlayerDetailUserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_blocked: bool
    access_revision: int
    created_at: datetime
    last_login_at: Optional[datetime] = None


class PlayerDetailOut(BaseModel):
    user: PlayerDetailUserOut
    scenario: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    recent_activity: list[dict[str, Any]] = []


class AccessUpdateIn(BaseModel):
    blocked: bool
    reason: str = Field(min_length=3, max_length=500)
    expected_access_revision: int


class LeaderboardAdjustmentIn(BaseModel):
    expected_revision: int
    risk_score_override: Optional[str] = None
    resource_score_override: Optional[str] = None
    game_score_override: Optional[str] = None
    reason: str = Field(min_length=5, max_length=500)


class AuditEventOut(BaseModel):
    id: int
    actor_user_id: Optional[int] = None
    round_id: Optional[int] = None
    scenario_id: Optional[int] = None
    event_type: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    reason: Optional[str] = None
    request_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime


class AuditPageOut(BaseModel):
    rows: list[AuditEventOut]
    next_cursor: Optional[str] = None
