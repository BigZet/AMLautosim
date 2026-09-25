"""Stable resource contracts shared by preview, autosave and results."""

from typing import Literal

from pydantic import BaseModel, model_serializer


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
    target_outflow: str | None = None
    purchase_outflow: str | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


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


class PurchaseImpactOut(BaseModel):
    merchant_id: str
    category: str | None


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
    purchase: PurchaseImpactOut | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        result = handler(self)
        # JSONB reorders object keys; preview and persisted results must agree.
        result["detail_factors"] = sorted(
            result["detail_factors"], key=lambda factor: factor["field_key"]
        )
        if self.purchase is None:
            result.pop("purchase", None)
        return result


class TimelineStepOut(BaseModel):
    step_id: str
    step_index: int
    occurred_at: str
    elapsed_minutes: int
    interval_minutes: int | None
    waiting_time_cost: int
    operation_time_cost: int
    time_of_day: Literal["night", "day", "evening"]
    pace: Literal["rapid", "normal", "spaced"] | None


class TimelineOut(BaseModel):
    version: str
    timezone: str
    steps: list[TimelineStepOut]


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

    timeline: TimelineOut | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        result = handler(self)
        if self.timeline is None:
            result.pop("timeline", None)
        return result
