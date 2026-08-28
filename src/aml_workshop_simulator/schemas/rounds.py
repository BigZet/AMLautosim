from __future__ import annotations

from typing import Any, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class RoundPublicOut(BaseModel):
    id: int
    title: str
    status: str
    config_version: Optional[str] = None
    activated_at: Optional[datetime] = None
    game_config: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class RoundSummaryOut(BaseModel):
    id: int
    title: str
    status: str
    scenario_status: Optional[str] = None
    result_available: bool = False
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RoundSummaryPageOut(BaseModel):
    rows: list[RoundSummaryOut]
    next_cursor: Optional[str] = None


class ActionCardOut(BaseModel):
    id: int
    code: str
    version: int
    title: str
    description: Optional[str] = ""
    category: str
    flow: str
    risk_weight: str
    costs: dict[str, int]
    fee_rate: str
    min_amount: str
    max_amount: str
    max_frequency: int
    round_frequency_limit: int = 3
    requires_card_code: Optional[str] = None
    channels: list[str] = []
    fields: list[dict[str, Any]] = []
    context_fields: list[dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)
