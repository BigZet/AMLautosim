"""Which operation parameters a concrete round exposes to the participant.

A card version declares *everything* it could ever accept (`domain.catalog`).
A round snapshot decides which of those card versions are playable and, for
each of them, the small set of parameters the participant may actually edit.
Everything else is pinned to a stable server-side default so the resource
calculation and the scoring stay deterministic.

Parameter keys live in one flat namespace so a round config can name them
without ambiguity:

``channel``                 the operation channel (stored as ``context.channel``)
``context.<key>``           one of the shared context fields
``action.<key>``            one card-specific action detail

A round config written before this module existed carries no ``operations``
block. Such a round is *legacy*: every declared parameter stays editable, which
is exactly what its stored drafts were validated against.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

PARAM_CHANNEL = "channel"
CONTEXT_PREFIX = "context."
ACTION_PREFIX = "action."

#: Amount and frequency are always their own controls; on top of them a round
#: may expose at most this many parameters per operation.
MAX_VISIBLE_PARAMS = 2

#: Numeric card attributes a round is allowed to re-tune for its own snapshot.
CARD_OVERRIDE_KEYS: tuple[str, ...] = (
    "min_amount",
    "max_amount",
    "max_frequency",
    "round_frequency_limit",
    "energy_cost",
    "time_cost",
    "trust_cost",
    "fee_rate",
)

DECIMAL_OVERRIDE_KEYS = frozenset({"min_amount", "max_amount", "fee_rate"})


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
        return ("context", param[len(CONTEXT_PREFIX):])
    if param.startswith(ACTION_PREFIX):
        return ("action", param[len(ACTION_PREFIX):])
    raise ValueError(f"unknown parameter namespace: {param!r}")


def declared_params(spec: CardContract) -> tuple[str, ...]:
    """Every parameter key a card version could expose, in display order."""
    return (
        (PARAM_CHANNEL,)
        + tuple(context_param(item["key"]) for item in spec.context_fields)
        + tuple(action_param(item["key"]) for item in spec.fields)
    )


@dataclass(frozen=True)
class OperationPolicy:
    """Round-scoped rules for one card version."""

    code: str
    version: int
    visible_params: tuple[str, ...]
    show_frequency: bool
    #: Value every *non visible* parameter is pinned to for this round.
    pinned: dict[str, Any] = field(default_factory=dict)
    #: Numeric card attributes this round overrides.
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int]:
        return (self.code, self.version)

    def is_visible(self, param: str) -> bool:
        return param in self.visible_params

    def default_for(self, param: str) -> Any:
        return self.pinned.get(param)


@dataclass(frozen=True)
class RoundPolicy:
    """Resolved ``operations`` block of one round snapshot."""

    legacy: bool
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
            # Legacy snapshot: no operations block, so nothing is hidden.
            return cls(
                legacy=True,
                operations={key: _legacy_policy(spec) for key, spec in specs.items()},
            )

        operations: dict[tuple[str, int], OperationPolicy] = {}
        for entry in raw_operations:
            key = (str(entry["code"]), int(entry.get("version", 1)))
            spec = specs.get(key)
            if spec is None:
                continue
            operations[key] = restricted_policy(spec, entry)
        return cls(legacy=False, operations=operations)


def field_default(spec: CardContract, param: str) -> Any:
    """Catalog default of one parameter of a card version."""
    namespace, key = split_param(param)
    if namespace == "channel":
        return spec.channels[0] if spec.channels else None
    source = spec.context_fields if namespace == "context" else spec.fields
    for item in source:
        if item["key"] == key:
            return item.get("default")
    return None


def _legacy_policy(spec: CardContract) -> OperationPolicy:
    return OperationPolicy(
        code=spec.code,
        version=spec.version,
        visible_params=declared_params(spec),
        show_frequency=True,
        pinned={},
        overrides={},
    )


def restricted_policy(spec: CardContract, entry: Mapping[str, Any]) -> OperationPolicy:
    """One `operations[]` entry resolved against the card version contract."""
    declared = declared_params(spec)
    requested = entry.get("visible_params")
    if requested is None:
        requested = tuple(getattr(spec, "default_visible_params", ()) or ())
    wanted = {param for param in requested if param in declared}
    # Order the visible parameters the way the card declares them so the form
    # layout does not depend on how the administrator typed the list.
    visible = tuple(param for param in declared if param in wanted)

    pinned: dict[str, Any] = {}
    explicit_defaults = dict(entry.get("defaults") or {})
    for param in declared:
        if param in visible:
            continue
        if param in explicit_defaults:
            pinned[param] = explicit_defaults[param]
        else:
            pinned[param] = field_default(spec, param)

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
        show_frequency=bool(entry.get("show_frequency", True)),
        pinned=pinned,
        overrides=overrides,
    )


def operations_from_specs(
    specs: Sequence[CardContract],
    codes: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Default ``operations`` block for a fresh round configuration."""
    wanted = set(codes) if codes is not None else None
    block: list[dict[str, Any]] = []
    for spec in specs:
        if wanted is not None and spec.code not in wanted:
            continue
        declared = declared_params(spec)
        visible = [
            param
            for param in getattr(spec, "default_visible_params", ())
            if param in declared
        ]
        block.append(
            {
                "code": spec.code,
                "version": spec.version,
                "visible_params": visible,
                "show_frequency": bool(getattr(spec, "default_show_frequency", True)),
            }
        )
    return block
