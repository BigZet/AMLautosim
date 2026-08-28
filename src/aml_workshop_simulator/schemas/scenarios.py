"""Strict scenario DTOs.

Every input model forbids unknown fields, money is a `Decimal` serialised as a
fixed-point string, and the operation channel is the global `Channel` enum. The
subset of channels a concrete card version accepts is enforced by
`domain.rules` against the card contract stored in PostgreSQL, not here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from src.aml_workshop_simulator.domain.channels import Channel

StrictValue = str | bool | int | Decimal

STRICT = ConfigDict(extra="forbid")


class CardRef(BaseModel):
    """Reference to one immutable card version."""

    model_config = STRICT

    id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)


class OperationContext(BaseModel):
    """Common operation context shared by all cards."""

    model_config = STRICT

    country_risk: Literal["low", "medium", "high"] = "low"
    recipient_type: Literal[
        "known_counterparty", "new_counterparty", "anonymous_wallet"
    ] = "known_counterparty"
    time_of_day: Literal["day", "evening", "night"] = "day"
    velocity: Literal["spaced", "normal", "rapid"] = "normal"
    channel: Channel
    has_documents: bool = True


class ScenarioStepIn(BaseModel):
    """One instance of a card inside a participant chain."""

    model_config = STRICT

    step_id: UUID
    card: CardRef
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    frequency: int = Field(ge=1, le=20)
    context: OperationContext
    action_details: dict[str, StrictValue] = Field(default_factory=dict)

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"

    @field_serializer("step_id")
    def _serialize_step_id(self, value: UUID) -> str:
        return str(value)


class ScenarioPutIn(BaseModel):
    """Full idempotent replacement of the server draft."""

    model_config = STRICT

    expected_revision: int = Field(ge=0)
    client_mutation_id: UUID
    steps: list[ScenarioStepIn] = Field(default_factory=list, max_length=64)


class ScenarioSubmitIn(BaseModel):
    """Submit one stored revision."""

    model_config = STRICT

    expected_revision: int = Field(ge=1)


class ScenarioOut(BaseModel):
    """Canonical server scenario."""

    id: int
    round_id: int
    participant_id: int
    status: str
    revision: int
    steps: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime
    submitted_at: datetime | None = None
