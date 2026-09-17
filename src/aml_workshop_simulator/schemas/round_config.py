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
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.aml_workshop_simulator.core.game_config import LIMITS, load_config
from src.aml_workshop_simulator.domain.round_policy import (
    CARD_OVERRIDE_KEYS,
    split_param,
)
from src.aml_workshop_simulator.schemas.card_contract import (
    CardSnapshotOut,
)
from src.aml_workshop_simulator.schemas.game_rules import ResourceRulesIn, RiskRulesIn

from src.aml_workshop_simulator.domain.contract_versions import (
    LEGACY_CONTRACT_VERSION,
    contract_version,
)
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior

from src.aml_workshop_simulator.services.semantic_contract import BehaviorV9
from src.aml_workshop_simulator.services.aml_context import BehaviorV10, validate_context

STRICT = ConfigDict(extra="forbid")

CONFIG_SCHEMA_VERSION = LEGACY_CONTRACT_VERSION

#: Quota buckets an organiser can cap. They match `domain.rules.QUOTA_LABELS`.
QUOTA_CODES = ("cash", "anonymous")

RESOURCE_WEIGHT_KEYS = ("balance", "energy", "time", "fees", "available_steps")


def _money(value: Decimal) -> str:
    return f"{Decimal(value):.2f}"


class ResourcesIn(BaseModel):
    model_config = STRICT

    initial_balance: Decimal = Field(
        gt=0, le=Decimal(LIMITS["max_balance"]), decimal_places=2
    )
    initial_energy: int = Field(ge=1, le=LIMITS["max_resource"])
    initial_time: int = Field(ge=1, le=LIMITS["max_resource"])

    def dump(self) -> dict[str, Any]:
        return {
            "initial_balance": _money(self.initial_balance),
            "initial_energy": self.initial_energy,
            "initial_time": self.initial_time,
        }


class ObjectivesIn(BaseModel):
    model_config = STRICT

    target_outflow: Decimal = Field(
        gt=0, le=Decimal(LIMITS["max_balance"]), decimal_places=2
    )
    max_actions: int = Field(ge=1, le=LIMITS["max_actions"])

    def dump(self) -> dict[str, Any]:
        return {
            "target_outflow": _money(self.target_outflow),
            "max_actions": self.max_actions,
        }


class ConstraintsIn(BaseModel):
    model_config = STRICT

    max_identical_steps: int = Field(ge=1, le=LIMITS["max_actions"])
    max_night_operations: int = Field(ge=0, le=LIMITS["max_actions"])
    max_anonymous_operations: int = Field(ge=0, le=LIMITS["max_actions"])
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
            if not limit.is_finite() or limit < 0 or limit.as_tuple().exponent < -2:
                raise ValueError(
                    f"Лимит квоты «{code}»: ожидается неотрицательная конечная сумма с точностью до копейки."
                )
        return value

    def dump(self) -> dict[str, Any]:
        return {
            "max_identical_steps": self.max_identical_steps,
            "max_night_operations": self.max_night_operations,
            "max_anonymous_operations": self.max_anonymous_operations,
            "category_limits": {
                code: _money(limit)
                for code, limit in sorted(self.category_limits.items())
            },
        }


class OperationIn(BaseModel):
    """One playable card version and the parameters it exposes."""

    model_config = STRICT

    code: str = Field(min_length=1, max_length=80)
    version: int = Field(default=1, ge=1)
    visible_params: list[str] = Field(default_factory=list)

    min_amount: Decimal | None = Field(
        default=None, gt=0, le=Decimal(LIMITS["max_balance"]), decimal_places=2
    )
    max_amount: Decimal | None = Field(
        default=None, gt=0, le=Decimal(LIMITS["max_balance"]), decimal_places=2
    )
    max_occurrences: int | None = Field(default=None, ge=1, le=LIMITS["max_actions"])
    energy_cost: int | None = Field(default=None, ge=0, le=LIMITS["max_operation_cost"])
    time_cost: int | None = Field(default=None, ge=0, le=LIMITS["max_operation_cost"])
    fee_rate: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=6)

    risk_weight: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)

    @field_validator("visible_params")
    @classmethod
    def _valid_params(cls, value: list[str]) -> list[str]:
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
        return self

    def dump(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "version": self.version,
            "visible_params": list(self.visible_params),
        }
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
    rules: RiskRulesIn = Field(
        default_factory=lambda: RiskRulesIn.model_validate(
            load_config("risk_rules.json")
        )
    )
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
            "rules": self.rules.model_dump(mode="json"),
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
        if any(
            not weight.is_finite() or weight < 0 or weight > 1
            for weight in value.values()
        ):
            raise ValueError("Каждый вес должен быть конечным числом от 0 до 1.")
        if sum(value.values()) != Decimal("1"):
            raise ValueError("Веса лидерборда должны в сумме давать 1.")
        return value

    @field_validator("resource_weights")
    @classmethod
    def _resource_weights(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if set(value) != set(RESOURCE_WEIGHT_KEYS):
            raise ValueError(
                "Веса ресурсов: ожидаются ключи "
                + ", ".join(RESOURCE_WEIGHT_KEYS)
                + "."
            )
        if any(
            not weight.is_finite() or weight < 0 or weight > 1
            for weight in value.values()
        ):
            raise ValueError("Каждый вес должен быть конечным числом от 0 до 1.")
        if sum(value.values()) != Decimal("1"):
            raise ValueError("Веса ресурсов должны в сумме давать 1.")
        return value

    def dump(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "weights": {key: str(value) for key, value in sorted(self.weights.items())},
            "resource_weights": {
                key: str(value) for key, value in sorted(self.resource_weights.items())
            },
        }


class GameConfigIn(BaseModel):
    """Full round configuration as an organiser edits it."""

    model_config = STRICT

    schema_version: Literal[7] = CONFIG_SCHEMA_VERSION
    resources: ResourcesIn
    objectives: ObjectivesIn
    constraints: ConstraintsIn
    operations: list[OperationIn] = Field(
        min_length=1, max_length=LIMITS["max_operations"]
    )
    resource_rules: ResourceRulesIn = Field(
        default_factory=lambda: ResourceRulesIn.model_validate(
            load_config("resource_rules.json")
        )
    )
    ruleset_version: str = Field(min_length=1, max_length=64)
    scoring: ScoringIn
    leaderboard: LeaderboardIn

    @model_validator(mode="after")
    def _has_operations(self) -> GameConfigIn:
        if not self.operations:
            raise ValueError("Раунд должен содержать хотя бы одну операцию.")
        if self.schema_version == 7 and any(
            item.code == "purchase" for item in self.operations
        ):
            raise ValueError("Покупки недоступны в контракте v7")
        codes = [(item.code, item.version) for item in self.operations]
        if len(set(codes)) != len(codes):
            raise ValueError("Операция указана в конфигурации несколько раз.")
        return self

    def dump(self) -> dict[str, Any]:
        """Plain JSON snapshot stored in `rounds.game_config`."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "operations": [item.dump() for item in self.operations],
            "resource_rules": self.resource_rules.model_dump(mode="json"),
            "resources": self.resources.dump(),
            "objectives": self.objectives.dump(),
            "constraints": self.constraints.dump(),
            "ruleset_version": self.ruleset_version,
            "scoring": self.scoring.dump(),
            "leaderboard": self.leaderboard.dump(),
        }
        return payload


class GameConfigOut(GameConfigIn):
    """Stored configuration including the server-owned snapshot."""

    config_version: str
    card_snapshots: list[CardSnapshotOut]


class ExpandedGameConfigIn(GameConfigIn):
    """Readable development contract. Runtime availability is checked separately."""

    schema_version: Literal[8]
    behavior: ExpandedBehavior

    @model_validator(mode="after")
    def purchase_contract(self):
        for operation in self.operations:
            if operation.code == "purchase":
                if self.behavior.purchases is None:
                    raise ValueError("Покупка требует purchase-policy-v1")
                from src.aml_workshop_simulator.domain.catalog import catalog_entry

                if operation.version != 1:
                    raise ValueError("Неизвестная версия покупки")
                entry = catalog_entry("purchase", operation.version)
                for key in CARD_OVERRIDE_KEYS:
                    value = getattr(operation, key)
                    if value is not None and value != entry[key]:
                        raise ValueError(
                            f"Параметр покупки {key} зафиксирован в purchase-policy-v1"
                        )
        return self

    def dump(self) -> dict[str, Any]:
        return {**super().dump(), "behavior": self.behavior.model_dump(mode="json")}


class ExpandedGameConfigOut(ExpandedGameConfigIn):
    risk_model: dict[str, Any] | None = None
    config_version: str
    card_snapshots: list[CardSnapshotOut]


# V7 keeps its default for existing clients which omit schema_version.


class SemanticGameConfigIn(ExpandedGameConfigIn):
    schema_version: Literal[9]
    behavior: BehaviorV9


class SemanticGameConfigOut(SemanticGameConfigIn):
    risk_model: dict[str, Any] | None = None
    config_version: str
    card_snapshots: list[CardSnapshotOut]


class AMLGameConfigIn(ExpandedGameConfigIn):
    schema_version: Literal[10]
    behavior: BehaviorV10

    @model_validator(mode="after")
    def evidence_references(self):
        validate_context(self.behavior.aml_context.model_dump(mode="json"), self.dump())
        return self


class AMLGameConfigOut(AMLGameConfigIn):
    risk_model: dict[str, Any] | None = None
    config_version: str
    card_snapshots: list[CardSnapshotOut]


RoundConfigInput = Annotated[
    GameConfigIn | ExpandedGameConfigIn | SemanticGameConfigIn | AMLGameConfigIn,
    Field(discriminator="schema_version"),
]
RoundConfigOutput = GameConfigOut | ExpandedGameConfigOut | SemanticGameConfigOut | AMLGameConfigOut


def parse_game_config(
    value: dict[str, Any], *, stored: bool = False
) -> RoundConfigInput | RoundConfigOutput:
    """Explicit snapshot dispatch; never coerce an unsupported version to v7."""
    version = contract_version(value)
    if version == 7:
        model = GameConfigOut if stored else GameConfigIn
    elif version == 9:
        model = SemanticGameConfigOut if stored else SemanticGameConfigIn
    elif version == 10:
        model = AMLGameConfigOut if stored else AMLGameConfigIn
    else:
        model = ExpandedGameConfigOut if stored else ExpandedGameConfigIn
    return model.model_validate(value)
