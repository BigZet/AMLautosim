"""Which operation parameters a concrete round exposes to the participant.

A card version declares *everything* it could ever accept (`domain.catalog`).
A round snapshot decides which of those card versions are playable and, for
each of them, all declared parameters are editable. Legacy visibility lists
and pinned defaults no longer restrict participant input.

Parameter keys live in one flat namespace so a round config can name them
without ambiguity:

``channel``                 the operation channel (stored as ``context.channel``)
``context.<key>``           one of the shared context fields
``action.<key>``            one card-specific action detail

Every round explicitly declares the playable operations and their parameters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

PARAM_CHANNEL = "channel"
CONTEXT_PREFIX = "context."
ACTION_PREFIX = "action."

#: Numeric card attributes a round is allowed to re-tune for its own snapshot.
CARD_OVERRIDE_KEYS: tuple[str, ...] = (
    "min_amount",
    "max_amount",
    "max_occurrences",
    "energy_cost",
    "time_cost",
    "fee_rate",
    "risk_weight",
)

DECIMAL_OVERRIDE_KEYS = frozenset(
    {"min_amount", "max_amount", "fee_rate", "risk_weight"}
)


class CardContract(Protocol):
    """The part of a card version this module needs."""

    code: str
    version: int
    channels: tuple[str, ...]
    context_fields: tuple[dict[str, Any], ...]
    fields: tuple[dict[str, Any], ...]


def context_param(key: str) -> str:
    return f"{CONTEXT_PREFIX}{key}"


def action_param(key: str) -> str:
    return f"{ACTION_PREFIX}{key}"


def split_param(param: str) -> tuple[str, str]:
    """``("channel", "channel")``, ``("context", key)`` or ``("action", key)``."""
    if param == PARAM_CHANNEL:
        return ("channel", PARAM_CHANNEL)
    if param.startswith(CONTEXT_PREFIX):
        return ("context", param[len(CONTEXT_PREFIX) :])
    if param.startswith(ACTION_PREFIX):
        return ("action", param[len(ACTION_PREFIX) :])
    raise ValueError(f"unknown parameter namespace: {param!r}")


def declared_params(spec: CardContract) -> tuple[str, ...]:
    """Every parameter key a card version could expose, in display order."""
    declared = (
        ((PARAM_CHANNEL,) if spec.channels else ())
        + tuple(context_param(item["key"]) for item in spec.context_fields)
        + tuple(action_param(item["key"]) for item in spec.fields)
    )
    order = tuple(getattr(spec, "default_visible_params", ()))
    return tuple(p for p in order if p in declared) + tuple(
        p for p in declared if p not in order
    )


@dataclass(frozen=True)
class OperationPolicy:
    """Round-scoped rules for one card version."""

    code: str
    version: int
    visible_params: tuple[str, ...]
    #: Numeric card attributes this round overrides.
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int]:
        return (self.code, self.version)

    def is_visible(self, param: str) -> bool:
        return param in self.visible_params


@dataclass(frozen=True)
class RoundPolicy:
    """Resolved ``operations`` block of one round snapshot."""

    operations: dict[tuple[str, int], OperationPolicy]

    def enabled_keys(self) -> tuple[tuple[str, int], ...]:
        return tuple(self.operations)

    def is_enabled(self, key: tuple[str, int]) -> bool:
        return key in self.operations

    def for_card(self, key: tuple[str, int]) -> OperationPolicy | None:
        return self.operations.get(key)

    @classmethod
    def from_config(
        cls,
        game_config: Mapping[str, Any] | None,
        specs: Mapping[tuple[str, int], CardContract],
    ) -> RoundPolicy:
        """Build the policy for `game_config` against the pinned card versions."""
        config = dict(game_config or {})
        raw_operations = config.get("operations")

        if not raw_operations:
            raise ValueError("Round configuration must declare operations")

        operations: dict[tuple[str, int], OperationPolicy] = {}
        for entry in raw_operations:
            key = (str(entry["code"]), int(entry.get("version", 1)))
            spec = specs.get(key)
            if spec is None:
                continue
            operations[key] = restricted_policy(spec, entry)
        return cls(operations=operations)


def restricted_policy(spec: CardContract, entry: Mapping[str, Any]) -> OperationPolicy:
    """One `operations[]` entry resolved against the card version contract."""
    declared = declared_params(spec)
    visible = declared

    overrides: dict[str, Any] = {}
    for key in CARD_OVERRIDE_KEYS:
        value = entry.get(key)
        if value is None:
            continue
        overrides[key] = (
            Decimal(str(value)) if key in DECIMAL_OVERRIDE_KEYS else int(value)
        )

    return OperationPolicy(
        code=spec.code,
        version=spec.version,
        visible_params=visible,
        overrides=overrides,
    )
