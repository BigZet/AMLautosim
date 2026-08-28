from __future__ import annotations

from typing import Any, Optional, Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CardRef(BaseModel):
    id: Optional[int] = None
    code: str
    version: int = Field(default=1, ge=1)


class OperationContext(BaseModel):
    country_risk: Literal["low", "medium", "high"] = "low"
    recipient_type: Literal["known_counterparty",
                            "new_counterparty",
                            "anonymous_wallet"] = "known_counterparty"
    time_of_day: Literal["day", "evening", "night"] = "day"
    velocity: Literal["spaced", "normal", "rapid"] = "normal"
    channel: Literal["mobile", "web", "branch",
                     "atm", "exchange", "bank"] = "bank"
    has_documents: bool = True


class ScenarioStepIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    step_id: Optional[str] = None
    card_code: Optional[str] = None
    card: Optional[CardRef] = None
    amount: float = Field(gt=0)
    frequency: int = Field(default=1, ge=1, le=20)
    context: Optional[OperationContext] = None
    # Support flat context fields from MVP
    country_risk: Optional[str] = None
    recipient_type: Optional[str] = None
    time_of_day: Optional[str] = None
    velocity: Optional[str] = None
    channel: Optional[str] = None
    has_documents: Optional[bool] = None
    action_details: Optional[dict[str, Any]] = None
    details: Optional[dict[str, Any]] = None


class ScenarioPutIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    expected_revision: int = 0
    client_mutation_id: Optional[str] = None
    steps: list[ScenarioStepIn] = []


class ScenarioSubmitIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    expected_revision: int = 0


class ScenarioOut(BaseModel):
    id: int
    round_id: int
    participant_id: int
    status: str
    revision: int
    steps: list[dict[str, Any]] = []
    resources: dict[str, Any] = {}
    updated_at: datetime
    submitted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
