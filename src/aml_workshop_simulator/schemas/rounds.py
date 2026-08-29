from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RoundPublicOut(BaseModel):
    """Non-secret round configuration for the participant UI."""

    id: int
    title: str
    status: str
    config_version: str | None = None
    activated_at: datetime | None = None
    stopped_at: datetime | None = None
    completed_at: datetime | None = None
    game_config: dict[str, Any]

    @property
    def accepts_changes(self) -> bool:
        return self.status == "active"


class RoundSummaryOut(BaseModel):
    id: int
    title: str
    status: str
    scenario_status: str | None = None
    result_available: bool = False
    completed_at: datetime | None = None


class RoundSummaryPageOut(BaseModel):
    rows: list[RoundSummaryOut]
    next_cursor: str | None = None


class VisibleParamOut(BaseModel):
    """One control the participant is actually offered for an operation."""

    param: str
    key: str
    namespace: str
    label: str
    kind: str = "select"
    help: str | None = None
    default: Any = None
    options: list[dict[str, Any]] = Field(default_factory=list)


class ActionCardOut(BaseModel):
    """One immutable card version plus its round-resolved UI contract.

    `channels`, `fields` and `context_fields` come from the very
    `parameter_schema` the server validates against, so the UI cannot offer an
    option the API would reject. `visible_params` narrows that contract down to
    what *this round* exposes; everything else is pinned server-side and listed
    in `pinned_defaults`.
    """

    id: int
    code: str
    version: int
    title: str
    description: str = ""
    category: str
    flow: str
    risk_weight: str
    costs: dict[str, int]
    fee_rate: str
    min_amount: str
    max_amount: str
    max_frequency: int
    round_frequency_limit: int
    requires_card_code: str | None = None
    quota_category: str | None = None
    channels: list[str] = Field(default_factory=list)
    channel_labels: dict[str, str] = Field(default_factory=dict)
    fields: list[dict[str, Any]] = Field(default_factory=list)
    context_fields: list[dict[str, Any]] = Field(default_factory=list)
    visible_params: list[VisibleParamOut] = Field(default_factory=list)
    show_frequency: bool = True
    pinned_defaults: dict[str, Any] = Field(default_factory=dict)
