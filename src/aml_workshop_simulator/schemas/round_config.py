"""Typed round configuration.

`rounds.game_config` used to be an untyped `dict[str, Any]` that the admin UI
edited as raw JSON. It is now a strict model: every field an organiser can set
is declared here, validated here, and actually consumed by the API, the
validation, the resource calculation or the scoring. Nothing decorative is
accepted.

Money is a `Decimal` on the wire and a fixed-point string inside the stored
snapshot, exactly like every other monetary value in the system.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.aml_workshop_simulator.domain.round_policy import (
    CARD_OVERRIDE_KEYS,
    MAX_VISIBLE_PARAMS,
    split_param,
)

STRICT = ConfigDict(extra="forbid")

CONFIG_SCHEMA_VERSION = 4

#: Quota buckets an organiser can cap. They match `domain.rules.QUOTA_LABELS`.
QUOTA_CODES = ("cash", "anonymous")

RESOURCE_WEIGHT_KEYS = ("balance", "energy", "time", "fees", "available_steps")


def _money(value: Decimal) -> str:
    return f"{Decimal(value):.2f}"


class ResourcesIn(BaseModel):
    model_config = STRICT

    initial_balance: Decimal = Field(gt=0, le=Decimal("100000000"), decimal_places=2)
    initial_energy: int = Field(ge=1, le=200)
    initial_time: int = Field(ge=1, le=200)

    def dump(self) -> dict[str, Any]:
        return {
            "initial_balance": _money(self.initial_balance),
            "initial_energy": self.initial_energy,
            "initial_time": self.initial_time,
        }


class ObjectivesIn(BaseModel):
    model_config = STRICT

    target_outflow: Decimal = Field(gt=0, le=Decimal("100000000"), decimal_places=2)
    max_actions: int = Field(ge=1, le=64)

    def dump(self) -> dict[str, Any]:
        return {
            "target_outflow": _money(self.target_outflow),
            "max_actions": self.max_actions,
        }


class ConstraintsIn(BaseModel):
    model_config = STRICT

    max_identical_steps: int = Field(ge=1, le=64)
    max_night_operations: int = Field(ge=0, le=64)
    max_anonymous_operations: int = Field(ge=0, le=64)
    category_limits: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("category_limits")
    @classmethod
    def _known_quotas(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        unknown = sorted(set(value) - set(QUOTA_CODES))
        if unknown:
            raise ValueError(
                "Неизвестная квота: "
                + ", ".join(unknown)
                + ". Допустимы: "
                + ", ".join(QUOTA_CODES)
                + "."
            )
        for code, limit in value.items():
            if limit < 0:
                raise ValueError(f"Лимит квоты «{code}» не может быть отрицательным.")
        return value

    def dump(self) -> dict[str, Any]:
        return {
            "max_identical_steps": self.max_identical_steps,
            "max_night_operations": self.max_night_operations,
            "max_anonymous_operations": self.max_anonymous_operations,
            "category_limits": {
                code: _money(limit) for code, limit in sorted(self.category_limits.items())
            },
        }


class OperationIn(BaseModel):
    """One playable card version and the parameters it exposes."""

    model_config = STRICT

    code: str = Field(min_length=1, max_length=80)
    version: int = Field(default=1, ge=1)
    visible_params: list[str] = Field(default_factory=list)
    show_frequency: bool = True
    defaults: dict[str, Any] = Field(default_factory=dict)

    min_amount: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    max_amount: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    max_frequency: int | None = Field(default=None, ge=1, le=20)
    round_frequency_limit: int | None = Field(default=None, ge=1, le=64)
    energy_cost: int | None = Field(default=None, ge=0, le=50)
    time_cost: int | None = Field(default=None, ge=0, le=50)
    fee_rate: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=6)

    @field_validator("visible_params")
    @classmethod
    def _valid_params(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_VISIBLE_PARAMS:
            raise ValueError(
                f"Для одной операции можно показать не более {MAX_VISIBLE_PARAMS} "
                f"параметров, получено {len(value)}."
            )
        if len(set(value)) != len(value):
            raise ValueError("Параметры операции продублированы.")
        for param in value:
            try:
                split_param(param)
            except ValueError as error:
                raise ValueError(
                    f"Неизвестный параметр «{param}»: используйте channel, "
                    "context.<поле> или action.<поле>."
                ) from error
        return value

    @model_validator(mode="after")
    def _amount_range(self) -> OperationIn:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError(
                f"Операция «{self.code}»: минимальная сумма больше максимальной."
            )
        if (
            self.max_frequency is not None
            and self.round_frequency_limit is not None
            and self.round_frequency_limit < self.max_frequency
        ):
            raise ValueError(
                f"Операция «{self.code}»: лимит повторов за раунд меньше лимита "
                "повторов одного шага."
            )
        return self

    def dump(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "version": self.version,
            "visible_params": list(self.visible_params),
            "show_frequency": self.show_frequency,
        }
        if self.defaults:
            payload["defaults"] = dict(sorted(self.defaults.items()))
        for key in CARD_OVERRIDE_KEYS:
            value = getattr(self, key)
            if value is None:
                continue
            payload[key] = (
                f"{value:.6f}"
                if key == "fee_rate"
                else (_money(value) if isinstance(value, Decimal) else int(value))
            )
        return payload


class ScoringIn(BaseModel):
    model_config = STRICT

    version: str = Field(min_length=1, max_length=64)
    review_threshold: Decimal = Field(ge=0, le=100, decimal_places=2)
    suspicious_threshold: Decimal = Field(ge=0, le=100, decimal_places=2)

    @model_validator(mode="after")
    def _ordered(self) -> ScoringIn:
        if self.review_threshold >= self.suspicious_threshold:
            raise ValueError(
                "Порог «требует проверки» должен быть меньше порога «подозрительно»."
            )
        return self

    def dump(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "review_threshold": _money(self.review_threshold),
            "suspicious_threshold": _money(self.suspicious_threshold),
        }


class LeaderboardIn(BaseModel):
    model_config = STRICT

    version: str = Field(min_length=1, max_length=64)
    weights: dict[str, Decimal]
    resource_weights: dict[str, Decimal]

    @field_validator("weights")
    @classmethod
    def _board_weights(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if set(value) != {"stealth", "resources"}:
            raise ValueError("Веса лидерборда: ожидаются ключи stealth и resources.")
        if sum(value.values()) != Decimal("1"):
            raise ValueError("Веса лидерборда должны в сумме давать 1.")
        return value

    @field_validator("resource_weights")
    @classmethod
    def _resource_weights(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if set(value) != set(RESOURCE_WEIGHT_KEYS):
            raise ValueError(
                "Веса ресурсов: ожидаются ключи " + ", ".join(RESOURCE_WEIGHT_KEYS) + "."
            )
        if sum(value.values()) != Decimal("1"):
            raise ValueError("Веса ресурсов должны в сумме давать 1.")
        return value

    def dump(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "weights": {key: f"{value:.2f}" for key, value in sorted(self.weights.items())},
            "resource_weights": {
                key: f"{value:.2f}" for key, value in sorted(self.resource_weights.items())
            },
        }


class GameConfigIn(BaseModel):
    """Full round configuration as an organiser edits it."""

    model_config = STRICT

    schema_version: int = Field(default=CONFIG_SCHEMA_VERSION, ge=4, le=4)
    resources: ResourcesIn
    objectives: ObjectivesIn
    constraints: ConstraintsIn
    operations: list[OperationIn] = Field(default_factory=list, max_length=64)
    ruleset_version: str = Field(min_length=1, max_length=64)
    scoring: ScoringIn
    leaderboard: LeaderboardIn
    #: Legacy pin list kept for configurations written before `operations`.
    card_versions: list[dict[str, Any]] | None = None
    #: Derived by the server on activation; accepted so a stored snapshot can be
    #: round-tripped through the editor without being rejected.
    config_version: str | None = None

    @model_validator(mode="after")
    def _has_operations(self) -> GameConfigIn:
        if not self.operations and not self.card_versions:
            raise ValueError(
                "Раунд должен содержать хотя бы одну операцию."
            )
        codes = [(item.code, item.version) for item in self.operations]
        if len(set(codes)) != len(codes):
            raise ValueError("Операция указана в конфигурации несколько раз.")
        return self

    def dump(self) -> dict[str, Any]:
        """Plain JSON snapshot stored in `rounds.game_config`."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "operations": [item.dump() for item in self.operations],
            "resources": self.resources.dump(),
            "objectives": self.objectives.dump(),
            "constraints": self.constraints.dump(),
            "ruleset_version": self.ruleset_version,
            "scoring": self.scoring.dump(),
            "leaderboard": self.leaderboard.dump(),
        }
        if self.card_versions:
            payload["card_versions"] = self.card_versions
        return payload


class RoundPresetIn(BaseModel):
    model_config = STRICT

    name: str = Field(min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    game_config: GameConfigIn


class RoundPresetUpdateIn(BaseModel):
    model_config = STRICT

    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    game_config: GameConfigIn | None = None


class RoundPresetOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    revision: int
    game_config: dict[str, Any]
    created_by_user_id: int
    updated_by_user_id: int
    created_at: Any
    updated_at: Any
