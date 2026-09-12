"""Game models for the scenario engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.channels import channel_label
from src.aml_workshop_simulator.domain.round_policy import (
    PARAM_CHANNEL,
    action_param,
    context_param,
)

RULESET_VERSION = "game-rules-v5"

SNAPSHOT_SCHEMA_VERSION = 5

MONEY = Decimal("0.01")

ZERO = Decimal("0.00")


def money(value: Any) -> Decimal:
    """Coerce to a two-decimal Decimal using banker's rounding."""
    if isinstance(value, Decimal):
        raw = value
    else:
        raw = Decimal(str(value))
    return raw.quantize(MONEY, rounding=ROUND_HALF_EVEN)


def _fmt_money(value: Decimal) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


@dataclass(frozen=True)
class Violation:
    """One actionable problem, bound to a concrete step and field."""

    reason: str
    message: str
    step_id: str | None = None
    step_index: int | None = None
    field: str | None = None
    current: str | None = None
    allowed: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class StructuralError(Exception):
    """Raised when the payload violates a card version contract."""

    def __init__(self, violations: Sequence[Violation]) -> None:
        super().__init__("scenario payload does not match the card contract")
        self.violations = list(violations)


@dataclass(frozen=True)
class CardSpec:
    """Immutable card version as stored in PostgreSQL and pinned by a round."""

    id: int
    code: str
    version: int
    title: str
    description: str
    category: str
    flow: str
    risk_weight: Decimal
    energy_cost: int
    time_cost: int
    fee_rate: Decimal
    min_amount: Decimal
    max_amount: Decimal
    max_occurrences: int
    requires_card_code: str | None
    quota_category: str | None
    channels: tuple[str, ...]
    context_fields: tuple[dict[str, Any], ...] = ()
    fields: tuple[dict[str, Any], ...] = ()
    default_visible_params: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, int]:
        return (self.code, self.version)

    def channel_labels(self) -> str:
        return ", ".join(f"«{channel_label(item)}»" for item in self.channels)

    def with_overrides(self, overrides: dict[str, Any] | None) -> CardSpec:
        """Card version re-tuned by the numeric overrides of one round."""
        if not overrides:
            return self
        return replace(self, **overrides)

    def field_spec(self, param: str) -> dict[str, Any] | None:
        """Declarative spec of one parameter, or None when not declared."""
        if param == PARAM_CHANNEL and self.channels:
            return {
                "key": PARAM_CHANNEL,
                "label": "Канал",
                "kind": "select",
                "default": self.channels[0] if self.channels else None,
                "options": [
                    {"value": item, "label": channel_label(item)}
                    for item in self.channels
                ],
            }
        for item in self.context_fields:
            if context_param(item["key"]) == param:
                return dict(item)
        for item in self.fields:
            if action_param(item["key"]) == param:
                return dict(item)
        return None


def card_spec_from_row(row: Any) -> CardSpec:
    """Build a `CardSpec` from an `action_cards` row (parameter_schema JSONB)."""
    schema: dict[str, Any] = dict(row.parameter_schema or {})
    return CardSpec(
        id=int(row.id),
        code=row.code,
        version=int(row.version),
        title=row.title,
        description=schema.get("description", ""),
        category=row.category,
        flow=row.flow,
        risk_weight=Decimal(str(row.risk_weight)),
        energy_cost=int(row.energy_cost),
        time_cost=int(row.time_cost),
        fee_rate=Decimal(str(row.fee_rate)),
        min_amount=Decimal(str(row.min_amount)),
        max_amount=Decimal(str(row.max_amount)),
        max_occurrences=int(schema["max_occurrences"]),
        requires_card_code=row.requires_card_code,
        quota_category=schema.get("quota_category"),
        channels=tuple(schema.get("channels", ())),
        context_fields=tuple(schema.get("context_fields", ())),
        fields=tuple(schema.get("fields", ())),
        default_visible_params=tuple(schema.get("default_visible_params", ())),
    )


def card_spec_from_catalog(entry: dict[str, Any], card_id: int) -> CardSpec:
    """Build a `CardSpec` straight from a catalog entry (tests and seeding)."""
    from src.aml_workshop_simulator.domain.catalog import build_parameter_schema

    schema = build_parameter_schema(entry)
    return CardSpec(
        id=card_id,
        code=entry["code"],
        version=entry["version"],
        title=entry["title"],
        description=entry["description"],
        category=entry["category"],
        flow=entry["flow"],
        risk_weight=entry["risk_weight"],
        energy_cost=entry["energy_cost"],
        time_cost=entry["time_cost"],
        fee_rate=entry["fee_rate"],
        min_amount=entry["min_amount"],
        max_amount=entry["max_amount"],
        max_occurrences=entry["max_occurrences"],
        requires_card_code=entry["requires_card_code"],
        quota_category=entry["quota_category"],
        channels=tuple(str(channel) for channel in entry["channels"]),
        context_fields=tuple(schema["context_fields"]),
        fields=tuple(schema["fields"]),
        default_visible_params=tuple(schema.get("default_visible_params", ())),
    )


QUOTA_LABELS = {
    "cash": "Наличные операции",
    "anonymous": "Анонимные получатели",
}


@dataclass(frozen=True)
class RoundRules:
    """Resolved round configuration used by the ruleset."""

    initial_balance: Decimal
    initial_energy: int
    initial_time: int
    target_outflow: Decimal
    max_actions: int
    max_identical_steps: int
    max_night_operations: int
    max_anonymous_operations: int
    category_limits: dict[str, Decimal] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> RoundRules:
        if config is None:
            raise ValueError("A complete round configuration is required")
        resources = config["resources"]
        objectives = config["objectives"]
        constraints = config["constraints"]
        raw_limits = constraints.get("category_limits", {}) or {}
        return cls(
            initial_balance=money(resources["initial_balance"]),
            initial_energy=int(resources["initial_energy"]),
            initial_time=int(resources["initial_time"]),
            target_outflow=money(objectives["target_outflow"]),
            max_actions=int(objectives["max_actions"]),
            max_identical_steps=int(constraints["max_identical_steps"]),
            max_night_operations=int(constraints["max_night_operations"]),
            max_anonymous_operations=int(constraints["max_anonymous_operations"]),
            category_limits={key: money(value) for key, value in raw_limits.items()},
        )


REFERENCE_GAME_CONFIG: dict[str, Any] = base_game_config()


def _step_label(index: int, spec: CardSpec | None) -> str:
    if spec is None:
        return f"Шаг {index}"
    return f"Шаг {index} «{spec.title}»"
