from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

STRICT = ConfigDict(extra="forbid")


class RoundCreateIn(BaseModel):
    model_config = STRICT

    title: str = Field(min_length=3, max_length=160)
    game_config: dict[str, Any]


class RoundUpdateIn(BaseModel):
    model_config = STRICT

    expected_config_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=160)
    game_config: dict[str, Any] | None = None


class RoundAdminOut(BaseModel):
    id: int
    title: str
    status: str
    config_revision: int
    game_config: dict[str, Any]
    scoring_summary: dict[str, Any] | None = None
    created_at: datetime
    activated_at: datetime | None = None
    completed_at: datetime | None = None


class RoundStatsOut(BaseModel):
    registered_users: int
    active_users: int
    blocked_users: int
    without_scenario: int
    draft_scenarios: int
    submitted_scenarios: int
    scored_scenarios: int
    public_leaderboard_rows: int
    last_scenario_update_at: datetime | None = None


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
    is_blocked: bool
    access_revision: int
    scenario_status: str = "none"
    scenario_revision: int | None = None
    game_score: str | None = None
    risk_label: str | None = None
    last_login_at: datetime | None = None


class PlayerSummaryPageOut(BaseModel):
    rows: list[PlayerSummaryOut]
    next_cursor: str | None = None


class PlayerDetailUserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_blocked: bool
    blocked_reason: str | None = None
    access_revision: int
    created_at: datetime
    last_login_at: datetime | None = None


class PlayerDetailOut(BaseModel):
    user: PlayerDetailUserOut
    scenario: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    recent_activity: list[dict[str, Any]] = Field(default_factory=list)


class AccessUpdateIn(BaseModel):
    model_config = STRICT

    blocked: bool
    reason: str = Field(min_length=10, max_length=500)
    expected_access_revision: int = Field(ge=0)


class LeaderboardAdjustmentIn(BaseModel):
    model_config = STRICT

    expected_revision: int = Field(ge=0)
    risk_score_override: Decimal | None = Field(default=None, ge=0, le=100)
    resource_score_override: Decimal | None = Field(default=None, ge=0, le=100)
    game_score_override: Decimal | None = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=10, max_length=500)


class LeaderboardAdjustmentOut(BaseModel):
    scenario_id: int
    revision: int
    base: dict[str, str]
    effective: dict[str, str]
    reason: str
    admin_user_id: int
    updated_at: datetime


class AuditEventOut(BaseModel):
    id: int
    actor_user_id: int | None = None
    round_id: int | None = None
    scenario_id: int | None = None
    event_type: str
    target_type: str | None = None
    target_id: str | None = None
    reason: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class AuditPageOut(BaseModel):
    rows: list[AuditEventOut]
    next_cursor: str | None = None
