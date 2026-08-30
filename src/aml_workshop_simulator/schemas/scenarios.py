"""Strict scenario DTOs.

Every input model forbids unknown fields, money is a `Decimal` serialised as a
fixed-point string, and the operation channel is the global `Channel` enum. The
subset of channels a concrete card version accepts is enforced by
`domain.rules` against the card contract stored in PostgreSQL, not here.

Context fields, `frequency` and the action details are **optional** on the
wire: a participant only sends the parameters their round actually exposes.
`services.scenario_service.canonical_steps` fills everything else from the
round policy, and `domain.rules` rejects any hidden parameter that was sent
with a value the round does not pin it to.
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
    """Common operation context shared by all cards.

    `None` means "not sent": the round policy decides the stored value.
    """

    model_config = STRICT

    recipient_type: (
        Literal["known_counterparty", "new_counterparty", "anonymous_wallet"] | None
    ) = None
    time_of_day: Literal["day", "evening", "night"] | None = None
    velocity: Literal["spaced", "normal", "rapid"] | None = None
    channel: Channel | None = None
    has_documents: bool | None = None


class ScenarioStepIn(BaseModel):
    """One instance of a card inside a participant chain."""

    model_config = STRICT

    step_id: UUID
    card: CardRef
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    frequency: int | None = Field(default=None, ge=1, le=20)
    context: OperationContext = Field(default_factory=OperationContext)
    action_details: dict[str, StrictValue] = Field(default_factory=dict)

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"

    @field_serializer("step_id")
    def _serialize_step_id(self, value: UUID) -> str:
        return str(value)


class ScenarioPutIn(BaseModel):
    """Full idempotent replacement of the server draft.

    A successful call that changes the payload appends a new immutable version;
    `label` names it in the participant's version history.
    """

    model_config = STRICT

    expected_revision: int = Field(ge=0)
    client_mutation_id: UUID
    steps: list[ScenarioStepIn] = Field(default_factory=list, max_length=64)
    label: str | None = Field(default=None, max_length=120)


class ScenarioPreviewIn(BaseModel):
    """Stateless evaluation of a candidate chain. Nothing is persisted."""

    model_config = STRICT

    steps: list[ScenarioStepIn] = Field(default_factory=list, max_length=64)


class ScenarioSubmitIn(BaseModel):
    """Submit one stored revision."""

    model_config = STRICT

    expected_revision: int = Field(ge=1)


class ScenarioRestoreIn(BaseModel):
    """Continue from an older saved version.

    The old version is copied into a **new** current version; nothing that was
    saved after it is deleted.
    """

    model_config = STRICT

    expected_revision: int = Field(ge=0)
    client_mutation_id: UUID
    label: str | None = Field(default=None, max_length=120)


class ScenarioVersionSummaryOut(BaseModel):
    """One row of the participant's saved-draft history."""

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
    balance_after: str | None = None
    energy_after: int | None = None
    time_after: int | None = None
    available_steps_after: int | None = None


class ScenarioVersionOut(ScenarioVersionSummaryOut):
    """One stored version with its full chain and resource snapshot."""

    steps: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)


class ScenarioVersionPageOut(BaseModel):
    rows: list[ScenarioVersionSummaryOut] = Field(default_factory=list)


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
    current_version_id: int | None = None
    submitted_revision: int | None = None
    version_count: int = 0


class ScenarioPreviewOut(BaseModel):
    """Server-computed snapshot of a chain that has not been saved yet."""

    resources: dict[str, Any] = Field(default_factory=dict)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
