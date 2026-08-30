"""Fail fast on invalid configuration files before seeding or serving requests."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aml_workshop_simulator.core.game_config import (
    LIMITS,
    base_game_config,
    load_config,
)
from aml_workshop_simulator.domain.channels import Channel
from aml_workshop_simulator.schemas.round_config import GameConfigIn


class OptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    label: str
    risk_points: Decimal = Field(default=0, allow_inf_nan=False)
    time_cost: int = Field(default=0, ge=0)
    energy_cost: int = Field(default=0, ge=0)
    description: str = ""


class ParameterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    kind: Literal["select", "toggle"]
    default: Any
    help: str | None = None
    required: bool = True
    options: list[OptionConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_default(self):
        values = [option.value for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate option: {self.key}")
        if self.kind == "select" and self.default not in values:
            raise ValueError(f"Invalid default: {self.key}")
        if self.kind == "toggle" and type(self.default) is not bool:
            raise ValueError(f"Boolean default required: {self.key}")
        return self


class CardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    version: int = Field(ge=1)
    title: str
    description: str
    category: str
    flow: Literal["credit", "debit", "neutral"]
    risk_weight: Decimal = Field(ge=0, le=100, decimal_places=2)
    energy_cost: int = Field(ge=0, le=LIMITS["max_operation_cost"])
    time_cost: int = Field(ge=0, le=LIMITS["max_operation_cost"])
    fee_rate: Decimal = Field(ge=0, le=1, decimal_places=6)
    min_amount: Decimal = Field(
        gt=0, le=Decimal(LIMITS["max_balance"]), decimal_places=2
    )
    max_amount: Decimal = Field(
        gt=0, le=Decimal(LIMITS["max_balance"]), decimal_places=2
    )
    max_frequency: int = Field(ge=1, le=LIMITS["max_frequency"])
    round_frequency_limit: int = Field(ge=1, le=LIMITS["max_actions"])
    requires_card_code: str | None
    quota_category: Literal["cash", "anonymous"] | None
    channels: list[Channel] = Field(min_length=1)
    default_visible_params: list[str] = Field(max_length=LIMITS["max_visible_params"])
    default_show_frequency: bool

    @model_validator(mode="after")
    def ranges(self):
        if (
            self.min_amount > self.max_amount
            or self.max_frequency > self.round_frequency_limit
        ):
            raise ValueError(f"Inconsistent card limits: {self.code}")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError(f"Duplicate channels: {self.code}")
        return self


def validate_configuration_files() -> None:
    from aml_workshop_simulator.domain.catalog import CARD_CATALOG
    from aml_workshop_simulator.domain.round_policy import declared_params
    from aml_workshop_simulator.domain.rules import card_spec_from_catalog

    config = GameConfigIn.model_validate(base_game_config())
    parameters = load_config("parameters.json")
    keys = set()
    for entry in CARD_CATALOG:
        card = CardConfig.model_validate(entry)
        key = (card.code, card.version)
        if key in keys:
            raise ValueError(f"Duplicate card: {key}")
        keys.add(key)
        spec = card_spec_from_catalog(entry, 1)
        if not set(card.default_visible_params) <= set(declared_params(spec)):
            raise ValueError(f"Unknown visible parameters: {key}")
        for field in (*spec.fields, *spec.context_fields):
            ParameterConfig.model_validate(field)
        if card.requires_card_code and card.requires_card_code not in {
            c["code"] for c in CARD_CATALOG
        }:
            raise ValueError(f"Unknown dependency: {card.requires_card_code}")
    for context in parameters["context_fields"].values():
        ParameterConfig.model_validate(context)
    if not {(o.code, o.version) for o in config.operations} <= keys:
        raise ValueError("Base round references unknown card versions")
