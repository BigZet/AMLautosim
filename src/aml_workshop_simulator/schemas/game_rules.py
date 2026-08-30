"""Validated, configurable coefficients of the resource and risk engines."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aml_workshop_simulator.domain.action_parameters import CONTEXT_FIELDS
from aml_workshop_simulator.domain.channels import ALL_CHANNELS

NonNegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Finite = Annotated[Decimal, Field(allow_inf_nan=False)]


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VelocityTimeIn(RuleModel):
    per_repeat: int
    per_extra_repeat: int


class DocumentTimeIn(RuleModel):
    minimum_gross: NonNegative
    time_cost: int = Field(ge=0)


def require_keys(value: dict, expected: set) -> dict:
    if set(value) != expected:
        raise ValueError("Ожидаются ключи: " + ", ".join(sorted(expected)))
    return value


class ResourceRulesIn(RuleModel):
    minimum_time_cost: int = Field(ge=0)
    channel_time: dict[str, Annotated[int, Field(ge=0)]]
    velocity_time: dict[str, VelocityTimeIn]
    documents: DocumentTimeIn

    @field_validator("channel_time")
    @classmethod
    def channels(cls, value: dict) -> dict:
        return require_keys(value, set(ALL_CHANNELS))

    @field_validator("velocity_time")
    @classmethod
    def velocities(cls, value: dict) -> dict:
        return require_keys(
            value, {o["value"] for o in CONTEXT_FIELDS["velocity"]["options"]}
        )


class DocumentRiskIn(RuleModel):
    minimum_gross: NonNegative
    present_large: Finite
    present_small: Finite
    absent_large: Finite
    absent_small: Finite


class SequenceRiskIn(RuleModel):
    repeated_min_amount: NonNegative
    repeated_points: NonNegative
    repeated_max_points: NonNegative
    turnover_ratio: NonNegative
    turnover_points: NonNegative


class RiskRulesIn(RuleModel):
    recipient_points: dict[str, Finite]
    time_of_day_points: dict[str, Finite]
    velocity_points: dict[str, Finite]
    channel_points: dict[str, Finite]
    amount_divisor: Decimal = Field(gt=0, allow_inf_nan=False)
    amount_max_points: NonNegative
    extra_repeat_points: NonNegative
    documents: DocumentRiskIn
    sequence: SequenceRiskIn
    explanation_factor_limit: int = Field(ge=1)

    @field_validator(
        "recipient_points", "time_of_day_points", "velocity_points", "channel_points"
    )
    @classmethod
    def point_keys(cls, value: dict, info) -> dict:
        context_key = {
            "recipient_points": "recipient_type",
            "time_of_day_points": "time_of_day",
            "velocity_points": "velocity",
        }.get(info.field_name)
        keys = (
            {o["value"] for o in CONTEXT_FIELDS[context_key]["options"]}
            if context_key
            else set(ALL_CHANNELS)
        )
        return require_keys(value, keys)
