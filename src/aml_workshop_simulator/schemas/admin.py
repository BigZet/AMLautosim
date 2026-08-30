from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aml_workshop_simulator.schemas.round_config import GameConfigIn

STRICT = ConfigDict(extra="forbid")


class RoundCreateIn(BaseModel):
    """Create a draft round, either from a preset or from an explicit config."""

    model_config = STRICT

    title: str = Field(min_length=3, max_length=160)
    game_config: GameConfigIn | None = None
    preset_id: int | None = Field(default=None, ge=1)


class RoundUpdateIn(BaseModel):
    model_config = STRICT

    expected_config_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=160)
    game_config: GameConfigIn | None = None


class RoundLifecycleIn(BaseModel):
    """Body of a stop command: destructive-looking actions need a confirmation."""

    model_config = STRICT

    confirm: bool = False
    reason: str | None = Field(default=None, max_length=500)


class RoundRestartIn(BaseModel):
    """Restart: a *new* round with the same configuration, nothing deleted."""

    model_config = STRICT

    confirm: bool = False
    title: str | None = Field(default=None, min_length=3, max_length=160)
    reason: str | None = Field(default=None, max_length=500)
    activate: bool = False


class RoundAdminOut(BaseModel):
    id: int
    title: str
    status: str
    config_revision: int
    game_config: dict[str, Any]
    scoring_summary: dict[str, Any] | None = None
    created_at: datetime
    activated_at: datetime | None = None
    stopped_at: datetime | None = None
    completed_at: datetime | None = None
    restarted_from_round_id: int | None = None
    preset_id: int | None = None


class RoundStatsOut(BaseModel):
    registered_users: int
    active_users: int
    blocked_users: int
    without_scenario: int
    draft_scenarios: int
    submitted_scenarios: int
    scored_scenarios: int
    public_leaderboard_rows: int
    saved_versions: int = 0
    last_scenario_update_at: datetime | None = None


class ScoringPlanOut(BaseModel):
    """What a scoring run would do, so the organiser can confirm it."""

    round_id: int
    round_status: str
    submitted_count: int
    excluded_draft_count: int
    already_scored_count: int
    can_score: bool
    blocker: str | None = None


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
    version_count: int = 0
    game_score: str | None = None
    risk_label: str | None = None
    registered_at: datetime | None = None
    last_login_at: datetime | None = None


class PlayerSummaryPageOut(BaseModel):
    rows: list[PlayerSummaryOut]
    next_cursor: str | None = None


class SessionInfoOut(BaseModel):
    """Technical session details. Administrator-only by design."""

    id: str
    audience: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    is_active: bool
    ip_address: str | None = None
    user_agent: str | None = None
    accept_language: str | None = None


class PlayerDetailUserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_blocked: bool
    blocked_reason: str | None = None
    access_revision: int
    created_at: datetime
    first_login_at: datetime | None = None
    last_login_at: datetime | None = None
    active_session_count: int = 0
    total_session_count: int = 0
    last_ip_address: str | None = None
    last_user_agent: str | None = None


class PlayerDetailOut(BaseModel):
    user: PlayerDetailUserOut
    scenario: dict[str, Any] | None = None
    versions: list[dict[str, Any]] = Field(default_factory=list)
    sessions: list[SessionInfoOut] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    recent_activity: list[dict[str, Any]] = Field(default_factory=list)


class ScenarioVersionAdminOut(BaseModel):
    """One stored draft version with every parameter of every step resolved."""

    id: int
    revision: int
    label: str | None = None
    step_count: int
    created_at: datetime
    created_by_user_id: int
    restored_from_revision: int | None = None
    is_current: bool = False
    is_submitted: bool = False
    valid: bool = False
    goal_reached: bool = False
    steps: list[dict[str, Any]] = Field(default_factory=list)
    described_steps: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)


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
