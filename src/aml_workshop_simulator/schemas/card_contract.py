"""Card metadata and server-owned catalog snapshot."""

from typing import Literal

from pydantic import BaseModel, Field

ParameterValue = str | bool | int | float


class OptionOut(BaseModel):
    value: str
    label: str
    risk_points: float = 0
    time_cost: int = 0
    energy_cost: int = 0
    description: str = ""


class ParameterOut(BaseModel):
    key: str
    label: str
    kind: Literal["select", "toggle"]
    default: ParameterValue
    help: str | None = None
    required: bool = True
    options: list[OptionOut] = Field(default_factory=list)


class CardCostsOut(BaseModel):
    energy: int
    time: int


class CardSnapshotOut(BaseModel):
    id: int
    code: str
    version: int
    title: str
    description: str
    category: str
    flow: Literal["credit", "debit", "neutral"]
    risk_weight: str
    energy_cost: int
    time_cost: int
    fee_rate: str
    min_amount: str
    max_amount: str
    max_occurrences: int
    requires_card_code: str | None
    quota_category: str | None
    channels: list[str]
    context_fields: list[ParameterOut]
    fields: list[ParameterOut]
    default_visible_params: list[str]
