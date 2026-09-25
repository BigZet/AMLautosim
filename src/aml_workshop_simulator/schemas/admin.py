from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.aml_workshop_simulator.schemas.history_summary import RoundContextOut
from src.aml_workshop_simulator.core.enums import RoundStatus
from src.aml_workshop_simulator.schemas.leaderboard import ResultOut
from src.aml_workshop_simulator.schemas.round_config import (
    RoundConfigInput,
    RoundConfigOutput,
)
from src.aml_workshop_simulator.schemas.scenarios import ScenarioOut
from src.aml_workshop_simulator.schemas.scoring import ScoringCountsOut, ScoringErrorOut

STRICT = ConfigDict(extra="forbid")


class RoundCreateIn(BaseModel):
    """Prepare the only round, using base settings unless provided."""

    model_config = STRICT

    title: str = Field(min_length=3, max_length=160)
    game_config: RoundConfigInput | None = None


class RoundUpdateIn(BaseModel):
    model_config = STRICT

    expected_config_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=160)
    game_config: RoundConfigInput | None = None


class RoundAdminOut(RoundContextOut):
    id: int
    title: str
    status: RoundStatus
    config_revision: int
    game_config: RoundConfigOutput
    scoring_summary: ScoringCountsOut | None = None
    closed_at: datetime | None = None
    scoring_started_at: datetime | None = None
    scoring_error: ScoringErrorOut | None = None
    created_at: datetime
    activated_at: datetime | None = None
    completed_at: datetime | None = None


class ScoringSummaryOut(BaseModel):
    round_id: int
    status: RoundStatus
    submitted_count: int
    scored_count: int
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
    scenario_status: Literal["none", "submitted", "scored"] = "none"
    game_score: str | None = None
    risk_label: str | None = None
    registered_at: datetime | None = None
    last_login_at: datetime | None = None


class PlayerSummaryPageOut(BaseModel):
    rows: list[PlayerSummaryOut]


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


class PlayerDetailOut(BaseModel):
    user: PlayerDetailUserOut
    scenario: ScenarioOut | None = None
    result: ResultOut | None = None


class AccessUpdateIn(BaseModel):
    model_config = STRICT

    blocked: bool
    reason: str = Field(min_length=10, max_length=500)
    expected_access_revision: int = Field(ge=0)


class ParticipantAccessOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_blocked: bool
    access_revision: int


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
    metadata: dict[str, JsonValue] | None = None
    created_at: datetime


class AuditPageOut(BaseModel):
    rows: list[AuditEventOut]
