"""Stable resource contracts shared by preview, autosave and results."""

from typing import Literal

from pydantic import BaseModel


class ViolationOut(BaseModel):
    reason: str
    message: str
    step_id: str | None = None
    step_index: int | None = None
    field: str | None = None
    current: str | None = None
    allowed: str | None = None


class ResourcesOut(BaseModel):
    balance: str
    energy: int
    time: int


class RemainingResourcesOut(ResourcesOut):
    available_steps: int


class TotalsOut(BaseModel):
    gross_inflow: str
    gross_outflow: str
    fees: str


class ObjectiveOut(BaseModel):
    target_outflow: str
    reached: bool


class LimitUsageOut(BaseModel):
    cash: str
    anonymous: str
    night_operations: int
    anonymous_operations: int
    actions: int


class LimitOut(BaseModel):
    code: str
    label: str
    kind: Literal["money", "count"]
    used: str
    limit: str
    remaining: str


class DetailFactorOut(BaseModel):
    field_key: str
    field_label: str
    value: str | bool | int
    value_label: str
    risk_points: str
    description: str


class StepImpactOut(BaseModel):
    step_id: str
    step_index: int
    card_code: str
    card_version: int
    card_title: str
    resources_before: ResourcesOut
    resources_after: ResourcesOut
    gross: str
    fee: str
    money_delta: str
    energy_cost: int
    time_cost: int
    detail_factors: list[DetailFactorOut]


class ResourceSnapshotOut(BaseModel):
    schema_version: int
    ruleset_version: str
    valid: bool
    resources_after: RemainingResourcesOut
    totals: TotalsOut
    objective: ObjectiveOut
    limit_usage: LimitUsageOut
    limits: list[LimitOut]
    violations: list[ViolationOut]
    per_step: list[StepImpactOut]
