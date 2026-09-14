"""Scenario DTOs: only card-declared context is stored; unknown fields are rejected."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_serializer,
    field_validator,
)

from src.aml_workshop_simulator.core.enums import ScenarioStatus
from src.aml_workshop_simulator.core.game_config import LIMITS
from src.aml_workshop_simulator.domain.action_parameters import CONTEXT_FIELDS
from src.aml_workshop_simulator.domain.channels import Channel
from src.aml_workshop_simulator.schemas.game_state import (
    ResourceSnapshotOut,
    ViolationOut,
)

StrictValue = str | bool | int | Decimal

STRICT = ConfigDict(extra="forbid")


class CardRef(BaseModel):
    """Reference to one immutable card version."""

    model_config = STRICT

    id: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)


RecipientType = StrEnum(
    "RecipientType",
    {o["value"]: o["value"] for o in CONTEXT_FIELDS["recipient_type"]["options"]},
)
TimeOfDay = StrEnum(
    "TimeOfDay",
    {o["value"]: o["value"] for o in CONTEXT_FIELDS["time_of_day"]["options"]},
)
Velocity = StrEnum(
    "Velocity", {o["value"]: o["value"] for o in CONTEXT_FIELDS["velocity"]["options"]}
)


class OperationContext(BaseModel):
    """Common operation context shared by all cards.

    Only card-declared fields are applicable; omitted applicable fields use catalog defaults.
    """

    model_config = STRICT

    recipient_type: RecipientType | None = None
    time_of_day: TimeOfDay | None = None
    velocity: Velocity | None = None
    channel: Channel | None = None


class ScenarioStepIn(BaseModel):
    """One instance of a card inside a participant chain."""

    model_config = STRICT

    step_id: UUID
    card: CardRef
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    context: OperationContext = Field(default_factory=OperationContext)
    action_details: dict[str, StrictValue] = Field(default_factory=dict)

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return f"{value:.2f}"

    @field_serializer("step_id")
    def _serialize_step_id(self, value: UUID) -> str:
        return str(value)


class StoredContext(OperationContext):
    """Sparse context: inapplicable keys are absent, not serialized as null."""

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


class StoredStep(ScenarioStepIn):
    context: StoredContext


class ExpandedOperationContext(BaseModel):
    model_config = STRICT
    channel: Channel | None = None


class ExpandedScenarioStepIn(ScenarioStepIn):
    """V8 input: identity references, never participant-supplied party properties."""

    context: ExpandedOperationContext = Field(default_factory=ExpandedOperationContext)
    sender_id: str | None = Field(default=None, min_length=1, max_length=80)
    recipient_id: str | None = Field(default=None, min_length=1, max_length=80)
    interval_minutes: Literal[1, 10, 60, 1440] | None = None

    @field_validator("interval_minutes", mode="before")
    @classmethod
    def strict_interval(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("Интервал задаётся целым числом минут")
        return value


ScenarioStepInput = Annotated[
    ScenarioStepIn | ExpandedScenarioStepIn, Field(union_mode="left_to_right")
]
ScenarioStepStored = Annotated[
    StoredStep | ExpandedScenarioStepIn, Field(union_mode="left_to_right")
]


class ScenarioPutIn(BaseModel):
    """Autosave the current editable scenario; revision protects against stale writes."""

    model_config = STRICT

    expected_revision: int = Field(ge=0)
    client_mutation_id: UUID
    steps: list[ScenarioStepInput] = Field(
        default_factory=list, max_length=LIMITS["max_actions"]
    )


class ScenarioPreviewIn(BaseModel):
    """Stateless evaluation of a candidate chain. Nothing is persisted."""

    model_config = STRICT

    steps: list[ScenarioStepInput] = Field(
        default_factory=list, max_length=LIMITS["max_actions"]
    )


class ScenarioSubmitIn(ScenarioPutIn):
    """Validate and submit the complete chain without a preceding autosave."""

    steps: list[ScenarioStepInput] = Field(max_length=LIMITS["max_actions"])


class ScenarioOut(BaseModel):
    """Canonical server scenario."""

    id: int
    round_id: int
    participant_id: int
    status: ScenarioStatus
    revision: int
    steps: list[ScenarioStepStored] = Field(default_factory=list)
    resources: ResourceSnapshotOut
    updated_at: datetime
    submitted_at: datetime | None = None
    can_edit: bool
    can_submit: bool
    blockers: list[ViolationOut]


class ScenarioPreviewOut(BaseModel):
    """Server-computed snapshot of a chain that has not been saved yet."""

    resources: ResourceSnapshotOut
    blockers: list[ViolationOut] = Field(default_factory=list)
    can_submit: bool
