"""Versioned game ruleset (`game-rules-v3`).

The ruleset draws a hard line between two classes of problem:

**Structural (card-contract) errors** — the payload does not match the card
version contract at all: unknown card, card id/code/version mismatch, duplicate
`step_id`, a channel the card version does not declare, an action-detail field
or option the card version does not declare, or a context field that does not
apply to the card. They are reported as `422` and never modify the stored
draft, exactly like a Pydantic failure: the UI only ever offers legal values,
so such a payload can only come from a malformed client.

**Business violations** — the chain is structurally well formed but breaks a
round rule: amount/frequency ranges, resource exhaustion, quotas, sequence
dependencies. The draft is still persisted with ``resources.valid = false`` and
the full violation list so no participant work is lost; only `submit` is
blocked.

All money is `Decimal`; every monetary result is quantised with banker's
rounding (`ROUND_HALF_EVEN`) to two decimal places.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from src.aml_workshop_simulator.domain.action_parameters import (
    CONTEXT_FIELDS,
    option_label,
)
from src.aml_workshop_simulator.domain.channels import channel_label
from src.aml_workshop_simulator.domain.round_policy import (
    PARAM_CHANNEL,
    OperationPolicy,
    RoundPolicy,
    action_param,
    context_param,
)

RULESET_VERSION = "game-rules-v3"
SNAPSHOT_SCHEMA_VERSION = 4

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


# --------------------------------------------------------------------------
# Violations
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Card specifications
# --------------------------------------------------------------------------


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
    max_frequency: int
    round_frequency_limit: int
    requires_card_code: str | None
    quota_category: str | None
    channels: tuple[str, ...]
    context_fields: tuple[dict[str, Any], ...] = ()
    fields: tuple[dict[str, Any], ...] = ()
    default_visible_params: tuple[str, ...] = ()
    default_show_frequency: bool = True

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
        if param == PARAM_CHANNEL:
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
        max_frequency=int(row.max_frequency),
        round_frequency_limit=int(schema.get("round_frequency_limit", row.max_frequency)),
        requires_card_code=row.requires_card_code,
        quota_category=schema.get("quota_category"),
        channels=tuple(schema.get("channels", ())),
        context_fields=tuple(schema.get("context_fields", ())),
        fields=tuple(schema.get("fields", ())),
        default_visible_params=tuple(schema.get("default_visible_params", ())),
        default_show_frequency=bool(schema.get("default_show_frequency", True)),
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
        max_frequency=entry["max_frequency"],
        round_frequency_limit=entry["round_frequency_limit"],
        requires_card_code=entry["requires_card_code"],
        quota_category=entry["quota_category"],
        channels=tuple(str(channel) for channel in entry["channels"]),
        context_fields=tuple(schema["context_fields"]),
        fields=tuple(schema["fields"]),
        default_visible_params=tuple(schema.get("default_visible_params", ())),
        default_show_frequency=bool(schema.get("default_show_frequency", True)),
    )


# --------------------------------------------------------------------------
# Round configuration
# --------------------------------------------------------------------------

QUOTA_LABELS = {
    "cash": "Наличные операции",
    "anonymous": "Анонимные получатели",
}

#: Channels that add extra handling time because a person is involved.
CHANNEL_TIME_MODIFIER: dict[str, int] = {"branch": 2}


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
        config = config or {}
        resources = config.get("resources", {})
        objectives = config.get("objectives", {})
        constraints = config.get("constraints", {})
        raw_limits = constraints.get("category_limits", {}) or {}
        return cls(
            initial_balance=money(resources.get("initial_balance", "250000.00")),
            initial_energy=int(resources.get("initial_energy", 14)),
            initial_time=int(resources.get("initial_time", 18)),
            target_outflow=money(objectives.get("target_outflow", "150000.00")),
            max_actions=int(objectives.get("max_actions", 8)),
            max_identical_steps=int(constraints.get("max_identical_steps", 2)),
            max_night_operations=int(constraints.get("max_night_operations", 2)),
            max_anonymous_operations=int(constraints.get("max_anonymous_operations", 2)),
            category_limits={key: money(value) for key, value in raw_limits.items()},
        )


def reference_operations() -> list[dict[str, Any]]:
    """Default `operations` block: four operations with two visible params."""
    from src.aml_workshop_simulator.domain.catalog import (
        CARD_CATALOG,
        DEFAULT_OPERATION_CODES,
        default_show_frequency,
        default_visible_params,
    )

    return [
        {
            "code": entry["code"],
            "version": entry["version"],
            "visible_params": list(default_visible_params(entry["code"])),
            "show_frequency": default_show_frequency(entry["code"]),
        }
        for entry in CARD_CATALOG
        if entry["code"] in DEFAULT_OPERATION_CODES
    ]


REFERENCE_GAME_CONFIG: dict[str, Any] = {
    "schema_version": 4,
    "operations": reference_operations(),
    "resources": {
        "initial_balance": "250000.00",
        "initial_energy": 14,
        "initial_time": 18,
    },
    "objectives": {"target_outflow": "150000.00", "max_actions": 8},
    "constraints": {
        "max_identical_steps": 2,
        "max_night_operations": 2,
        "max_anonymous_operations": 2,
        "category_limits": {
            "cash": "150000.00",
            "anonymous": "75000.00",
        },
    },
    "ruleset_version": RULESET_VERSION,
    "scoring": {
        "version": "risk-rules-v2",
        "review_threshold": "35.00",
        "suspicious_threshold": "65.00",
    },
    "leaderboard": {
        "version": "leaderboard-v2",
        "weights": {"stealth": "0.60", "resources": "0.40"},
        "resource_weights": {
            "balance": "0.27",
            "energy": "0.20",
            "time": "0.20",
            "fees": "0.20",
            "available_steps": "0.13",
        },
    },
}


# --------------------------------------------------------------------------
# Structural validation
# --------------------------------------------------------------------------


def _context_defaults() -> dict[str, Any]:
    return {key: spec["default"] for key, spec in CONTEXT_FIELDS.items()}


CONTEXT_DEFAULTS = _context_defaults()


def _step_label(index: int, spec: CardSpec | None) -> str:
    if spec is None:
        return f"Шаг {index}"
    return f"Шаг {index} «{spec.title}»"


def resolve_policy(
    card_specs: dict[tuple[str, int], CardSpec],
    game_config: dict[str, Any] | None,
    policy: RoundPolicy | None = None,
) -> RoundPolicy:
    """Policy of one round, defaulting to the legacy all-visible behaviour."""
    if policy is not None:
        return policy
    return RoundPolicy.from_config(game_config, card_specs)


def validate_structure(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    policy: RoundPolicy | None = None,
) -> list[Violation]:
    """Check every step against its card version contract and round policy.

    `steps` must already have passed Pydantic validation and normalisation, so
    each entry has `step_id`, `card`, `amount`, `frequency`, `context` and
    `action_details` with concrete values.
    """
    policy = resolve_policy(card_specs, None, policy)
    violations: list[Violation] = []
    seen_step_ids: set[str] = set()

    for index, step in enumerate(steps, start=1):
        step_id = str(step["step_id"])
        card_ref = step["card"]
        code = card_ref["code"]
        version = int(card_ref["version"])
        spec = card_specs.get((code, version))

        if step_id in seen_step_ids:
            violations.append(
                Violation(
                    reason="duplicate_step_id",
                    step_id=step_id,
                    step_index=index,
                    field="step_id",
                    current=step_id,
                    message=(
                        f"Шаг {index}: идентификатор шага {step_id} уже использован в этой "
                        "цепочке. Каждый шаг обязан иметь собственный step_id — "
                        "продублируйте шаг заново, чтобы получить новый идентификатор."
                    ),
                )
            )
        seen_step_ids.add(step_id)

        if spec is None:
            known = ", ".join(
                sorted({f"{key[0]} v{key[1]}" for key in card_specs}),
            )
            violations.append(
                Violation(
                    reason="unknown_card_version",
                    step_id=step_id,
                    step_index=index,
                    field="card",
                    current=f"{code} v{version}",
                    allowed=known,
                    message=(
                        f"Шаг {index}: карточка «{code}» версии {version} не входит в снимок "
                        f"активного раунда. Доступны: {known}. Пересоберите шаг из каталога "
                        "текущего раунда."
                    ),
                )
            )
            continue

        if not policy.legacy and not policy.is_enabled((code, version)):
            enabled = ", ".join(
                sorted(f"{item[0]} v{item[1]}" for item in policy.enabled_keys())
            )
            violations.append(
                Violation(
                    reason="card_not_in_round",
                    step_id=step_id,
                    step_index=index,
                    field="card",
                    current=f"{code} v{version}",
                    allowed=enabled,
                    message=(
                        f"Шаг {index}: операция «{spec.title}» отключена настройками "
                        f"этого раунда. Доступны: {enabled}. Замените шаг на одну из "
                        "доступных операций."
                    ),
                )
            )
            continue

        card_id = card_ref.get("id")
        if card_id is not None and int(card_id) != spec.id:
            violations.append(
                Violation(
                    reason="card_reference_mismatch",
                    step_id=step_id,
                    step_index=index,
                    field="card.id",
                    current=str(card_id),
                    allowed=str(spec.id),
                    message=(
                        f"{_step_label(index, spec)}: идентификатор карточки {card_id} не "
                        f"соответствует паре {code} v{version} (ожидается {spec.id}). "
                        "Обновите каталог карточек и добавьте шаг заново."
                    ),
                )
            )

        operation = policy.for_card((code, version))
        violations.extend(_validate_channel(index, step_id, step, spec, operation))
        violations.extend(_validate_frequency_visibility(index, step_id, step, spec, operation))
        violations.extend(_validate_context_fields(index, step_id, step, spec, operation))
        violations.extend(_validate_action_details(index, step_id, step, spec, operation))

    return violations


def _pinned_violation(
    index: int,
    step_id: str,
    spec: CardSpec,
    param: str,
    label: str,
    current: Any,
    expected: Any,
    field_name: str,
    current_label: str | None = None,
    expected_label: str | None = None,
) -> Violation:
    return Violation(
        reason="parameter_not_editable",
        step_id=step_id,
        step_index=index,
        field=field_name,
        current=str(current),
        allowed=str(expected),
        message=(
            f"{_step_label(index, spec)}, поле «{label}»: этот параметр закреплен "
            f"настройками раунда и допускает только значение "
            f"«{expected_label or expected}», получено «{current_label or current}». "
            "Уберите поле из шага или верните значение раунда."
        ),
    )


def _validate_channel(
    index: int,
    step_id: str,
    step: dict[str, Any],
    spec: CardSpec,
    operation: OperationPolicy | None,
) -> list[Violation]:
    channel = step["context"]["channel"]
    if channel not in spec.channels:
        return [
            Violation(
                reason="channel_not_allowed",
                step_id=step_id,
                step_index=index,
                field="context.channel",
                current=channel,
                allowed=", ".join(spec.channels),
                message=(
                    f"{_step_label(index, spec)}, поле «Канал»: значение "
                    f"«{channel_label(channel)}» недоступно для этой карточки. "
                    f"Допустимые каналы: {spec.channel_labels()}. "
                    "Выберите один из допустимых каналов и сохраните шаг заново."
                ),
            )
        ]
    if operation is not None and not operation.is_visible(PARAM_CHANNEL):
        expected = operation.default_for(PARAM_CHANNEL)
        if expected is not None and channel != expected:
            return [
                _pinned_violation(
                    index, step_id, spec, PARAM_CHANNEL, "Канал", channel, expected,
                    "context.channel",
                    current_label=channel_label(channel),
                    expected_label=channel_label(str(expected)),
                )
            ]
    return []


def _validate_frequency_visibility(
    index: int,
    step_id: str,
    step: dict[str, Any],
    spec: CardSpec,
    operation: OperationPolicy | None,
) -> list[Violation]:
    if operation is None or operation.show_frequency:
        return []
    frequency = int(step["frequency"])
    if frequency == 1:
        return []
    return [
        Violation(
            reason="frequency_not_editable",
            step_id=step_id,
            step_index=index,
            field="frequency",
            current=str(frequency),
            allowed="1",
            message=(
                f"{_step_label(index, spec)}, поле «Повторы»: в этом раунде операция "
                f"выполняется один раз, получено {frequency}. Верните значение 1 или "
                "добавьте отдельный шаг."
            ),
        )
    ]


def _validate_context_fields(
    index: int,
    step_id: str,
    step: dict[str, Any],
    spec: CardSpec,
    operation: OperationPolicy | None,
) -> list[Violation]:
    """Every context field the participant may not edit must hold its value."""
    declared = {item["key"] for item in spec.context_fields}
    violations: list[Violation] = []
    for key, default in CONTEXT_DEFAULTS.items():
        label = CONTEXT_FIELDS[key]["label"]
        param = context_param(key)
        if key not in declared:
            value = step["context"].get(key, default)
            if value == default:
                continue
            violations.append(
                Violation(
                    reason="context_field_not_applicable",
                    step_id=step_id,
                    step_index=index,
                    field=f"context.{key}",
                    current=str(value),
                    allowed=str(default),
                    message=(
                        f"{_step_label(index, spec)}, поле «{label}»: карточка не использует "
                        f"этот признак, поэтому допустимо только значение по умолчанию "
                        f"«{default}», получено «{value}». Уберите поле из шага или верните "
                        "значение по умолчанию."
                    ),
                )
            )
            continue
        if operation is None or operation.is_visible(param):
            continue
        expected = operation.default_for(param)
        value = step["context"].get(key, expected)
        if expected is None or value == expected:
            continue
        violations.append(
            _pinned_violation(
                index, step_id, spec, param, label, value, expected, f"context.{key}"
            )
        )
    return violations


def _validate_action_details(
    index: int,
    step_id: str,
    step: dict[str, Any],
    spec: CardSpec,
    operation: OperationPolicy | None,
) -> list[Violation]:
    details: dict[str, Any] = dict(step.get("action_details") or {})
    violations: list[Violation] = []
    declared = {item["key"]: item for item in spec.fields}

    for key in sorted(set(details) - set(declared)):
        violations.append(
            Violation(
                reason="unknown_action_parameter",
                step_id=step_id,
                step_index=index,
                field=f"action_details.{key}",
                current=str(details[key]),
                allowed=", ".join(sorted(declared)) or "—",
                message=(
                    f"{_step_label(index, spec)}: поле «{key}» не определено для этой карточки. "
                    f"Допустимые поля: {', '.join(sorted(declared)) or 'нет'}. "
                    "Удалите лишнее поле из шага."
                ),
            )
        )

    for key, field_spec in declared.items():
        param = action_param(key)
        hidden = operation is not None and not operation.is_visible(param)
        if hidden:
            expected = operation.default_for(param)
            if key in details and expected is not None and details[key] != expected:
                violations.append(
                    _pinned_violation(
                        index,
                        step_id,
                        spec,
                        param,
                        field_spec["label"],
                        details[key],
                        expected,
                        f"action_details.{key}",
                        current_label=option_label([field_spec], key, details[key]),
                        expected_label=option_label([field_spec], key, expected),
                    )
                )
            continue

        required = bool(field_spec.get("required", True))
        if key not in details:
            if required:
                violations.append(
                    Violation(
                        reason="missing_action_parameter",
                        step_id=step_id,
                        step_index=index,
                        field=f"action_details.{key}",
                        current=None,
                        allowed=", ".join(
                            str(option["value"]) for option in field_spec.get("options", [])
                        ),
                        message=(
                            f"{_step_label(index, spec)}, поле «{field_spec['label']}»: "
                            "обязательный параметр не заполнен. Выберите одно из значений: "
                            + ", ".join(
                                f"«{option['label']}»"
                                for option in field_spec.get("options", [])
                            )
                            + "."
                        ),
                    )
                )
            continue

        options = field_spec.get("options") or []
        if options:
            allowed_values = {option["value"] for option in options}
            value = details[key]
            if value not in allowed_values:
                violations.append(
                    Violation(
                        reason="invalid_action_parameter",
                        step_id=step_id,
                        step_index=index,
                        field=f"action_details.{key}",
                        current=str(value),
                        allowed=", ".join(sorted(str(item) for item in allowed_values)),
                        message=(
                            f"{_step_label(index, spec)}, поле «{field_spec['label']}»: "
                            f"значение «{value}» недопустимо. Выберите одно из значений: "
                            + ", ".join(f"«{option['label']}»" for option in options)
                            + "."
                        ),
                    )
                )
    return violations


# --------------------------------------------------------------------------
# Action-detail effects
# --------------------------------------------------------------------------


def action_detail_effects(spec: CardSpec, details: dict[str, Any]) -> dict[str, Any]:
    """Resource and risk effects of the selected action details."""
    result: dict[str, Any] = {
        "risk_points": ZERO,
        "time_cost": 0,
        "energy_cost": 0,
        "factors": [],
    }
    for field_spec in spec.fields:
        key = field_spec["key"]
        if key not in details:
            continue
        value = details[key]
        option = next(
            (item for item in field_spec.get("options", []) if item["value"] == value),
            None,
        )
        if option is None:
            continue
        points = Decimal(str(option.get("risk_points", 0)))
        result["factors"].append(
            {
                "field_key": key,
                "field_label": field_spec["label"],
                "value": value,
                "value_label": option["label"],
                "risk_points": points,
                "description": option.get("description", ""),
            }
        )
        result["risk_points"] += points
        result["time_cost"] += int(option.get("time_cost", 0))
        result["energy_cost"] += int(option.get("energy_cost", 0))
    return result


def action_detail_summary(spec: CardSpec, details: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "label": field_spec["label"],
            "value": option_label([field_spec], field_spec["key"], details[field_spec["key"]]),
        }
        for field_spec in spec.fields
        if field_spec["key"] in details
    ]


# --------------------------------------------------------------------------
# Business evaluation
# --------------------------------------------------------------------------


def evaluate_scenario(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    game_config: dict[str, Any] | None,
    policy: RoundPolicy | None = None,
) -> dict[str, Any]:
    """Compute the canonical resource snapshot for a structurally valid chain.

    Raises `StructuralError` when the payload breaks a card version contract.
    """
    policy = resolve_policy(card_specs, game_config, policy)
    structural = validate_structure(steps, card_specs, policy)
    if structural:
        raise StructuralError(structural)

    rules = RoundRules.from_config(game_config)
    violations: list[Violation] = []

    balance = rules.initial_balance
    energy = rules.initial_energy
    time_left = rules.initial_time
    inflow = ZERO
    outflow = ZERO
    fees = ZERO
    night_operations = 0
    anonymous_operations = 0
    previous_code: str | None = None
    identical_streak = 0
    card_frequencies: dict[str, int] = {}
    quota_usage: dict[str, Decimal] = {key: ZERO for key in QUOTA_LABELS}
    quota_reported: set[str] = set()
    per_step: list[dict[str, Any]] = []

    if len(steps) > rules.max_actions:
        violations.append(
            Violation(
                reason="max_actions_exceeded",
                field="steps",
                current=str(len(steps)),
                allowed=str(rules.max_actions),
                message=(
                    f"В цепочке {len(steps)} шагов, а раунд допускает не более "
                    f"{rules.max_actions}. Удалите лишние шаги."
                ),
            )
        )

    for index, step in enumerate(steps, start=1):
        step_id = str(step["step_id"])
        card_key = (step["card"]["code"], int(step["card"]["version"]))
        operation = policy.for_card(card_key)
        spec = card_specs[card_key].with_overrides(
            operation.overrides if operation else None
        )
        resources_before = {
            "balance": str(balance),
            "energy": energy,
            "time": time_left,
        }
        amount = money(step["amount"])
        frequency = int(step["frequency"])
        context = step["context"]
        channel = context["channel"]
        recipient_type = context.get("recipient_type", CONTEXT_DEFAULTS["recipient_type"])
        time_of_day = context.get("time_of_day", CONTEXT_DEFAULTS["time_of_day"])
        velocity = context.get("velocity", CONTEXT_DEFAULTS["velocity"])
        has_documents = bool(context.get("has_documents", CONTEXT_DEFAULTS["has_documents"]))
        details = dict(step.get("action_details") or {})
        effects = action_detail_effects(spec, details)

        gross = money(amount * frequency)
        fee = money(gross * spec.fee_rate)

        # ---- per-step limits ------------------------------------------------
        if amount < spec.min_amount or amount > spec.max_amount:
            violations.append(
                Violation(
                    reason="amount_out_of_range",
                    step_id=step_id,
                    step_index=index,
                    field="amount",
                    current=str(amount),
                    allowed=f"{spec.min_amount}..{spec.max_amount}",
                    message=(
                        f"{_step_label(index, spec)}, поле «Сумма»: указано "
                        f"{_fmt_money(amount)}, допустимо от {_fmt_money(spec.min_amount)} "
                        f"до {_fmt_money(spec.max_amount)} за один повтор. "
                        "Измените сумму в допустимый диапазон."
                    ),
                )
            )
        if frequency > spec.max_frequency:
            violations.append(
                Violation(
                    reason="frequency_out_of_range",
                    step_id=step_id,
                    step_index=index,
                    field="frequency",
                    current=str(frequency),
                    allowed=f"1..{spec.max_frequency}",
                    message=(
                        f"{_step_label(index, spec)}, поле «Повторы»: указано {frequency}, "
                        f"для этой операции допустимо не более {spec.max_frequency} повторов "
                        "в одном шаге. Уменьшите число повторов или разбейте шаг."
                    ),
                )
            )

        card_frequencies[spec.code] = card_frequencies.get(spec.code, 0) + frequency
        if card_frequencies[spec.code] > spec.round_frequency_limit:
            violations.append(
                Violation(
                    reason="round_frequency_limit_exceeded",
                    step_id=step_id,
                    step_index=index,
                    field="frequency",
                    current=str(card_frequencies[spec.code]),
                    allowed=str(spec.round_frequency_limit),
                    message=(
                        f"{_step_label(index, spec)}: суммарно по карточке «{spec.title}» "
                        f"набрано {card_frequencies[spec.code]} повторов за раунд, лимит — "
                        f"{spec.round_frequency_limit}. Уменьшите повторы в этом или "
                        "предыдущих шагах этой карточки."
                    ),
                )
            )

        # ---- sequence rules -------------------------------------------------
        if previous_code == spec.code:
            identical_streak += 1
        else:
            identical_streak = 1
            previous_code = spec.code
        if identical_streak > rules.max_identical_steps:
            violations.append(
                Violation(
                    reason="identical_streak_exceeded",
                    step_id=step_id,
                    step_index=index,
                    field="card",
                    current=str(identical_streak),
                    allowed=str(rules.max_identical_steps),
                    message=(
                        f"{_step_label(index, spec)}: подряд идет {identical_streak} одинаковых "
                        f"операций, допустимо не более {rules.max_identical_steps}. "
                        "Переставьте шаги так, чтобы между ними была другая операция."
                    ),
                )
            )

        if time_of_day == "night":
            night_operations += 1
            if night_operations > rules.max_night_operations:
                violations.append(
                    Violation(
                        reason="night_operations_exceeded",
                        step_id=step_id,
                        step_index=index,
                        field="context.time_of_day",
                        current=str(night_operations),
                        allowed=str(rules.max_night_operations),
                        message=(
                            f"{_step_label(index, spec)}, поле «Время операции»: это "
                            f"{night_operations}-я ночная операция, за раунд допустимо не более "
                            f"{rules.max_night_operations}. Перенесите операцию на день или вечер."
                        ),
                    )
                )

        if recipient_type == "anonymous_wallet":
            anonymous_operations += 1
            if anonymous_operations > rules.max_anonymous_operations:
                violations.append(
                    Violation(
                        reason="anonymous_operations_exceeded",
                        step_id=step_id,
                        step_index=index,
                        field="context.recipient_type",
                        current=str(anonymous_operations),
                        allowed=str(rules.max_anonymous_operations),
                        message=(
                            f"{_step_label(index, spec)}, поле «Получатель»: это "
                            f"{anonymous_operations}-я операция на анонимного получателя, "
                            f"за раунд допустимо не более {rules.max_anonymous_operations}. "
                            "Выберите известного контрагента."
                        ),
                    )
                )

        # ---- resource costs -------------------------------------------------
        energy_cost = spec.energy_cost * frequency + effects["energy_cost"]
        velocity_time = {
            "spaced": frequency,
            "normal": 0,
            "rapid": -max(0, frequency - 1),
        }.get(velocity, 0)
        document_time = 1 if has_documents and gross >= Decimal("75000") else 0
        channel_time = CHANNEL_TIME_MODIFIER.get(channel, 0)
        time_cost = max(
            1,
            spec.time_cost * frequency
            + velocity_time
            + document_time
            + channel_time
            + effects["time_cost"],
        )
        # ---- money ----------------------------------------------------------
        if spec.flow == "credit":
            money_delta = money(gross - fee)
            inflow = money(inflow + gross)
        elif spec.flow == "debit":
            money_delta = money(-(gross + fee))
            outflow = money(outflow + gross)
        else:  # neutral
            money_delta = money(-fee)

        # ---- quotas ---------------------------------------------------------
        if spec.quota_category:
            quota_usage[spec.quota_category] = money(
                quota_usage[spec.quota_category] + gross
            )
        if recipient_type == "anonymous_wallet":
            quota_usage["anonymous"] = money(quota_usage["anonymous"] + gross)
        for quota_code, limit in rules.category_limits.items():
            if quota_code not in quota_usage:
                continue
            if quota_usage[quota_code] > limit and quota_code not in quota_reported:
                quota_reported.add(quota_code)
                violations.append(
                    Violation(
                        reason="category_limit_exceeded",
                        step_id=step_id,
                        step_index=index,
                        field="amount",
                        current=str(quota_usage[quota_code]),
                        allowed=str(limit),
                        message=(
                            f"{_step_label(index, spec)}: квота «{QUOTA_LABELS[quota_code]}» "
                            f"использована на {_fmt_money(quota_usage[quota_code])} при лимите "
                            f"{_fmt_money(limit)} за раунд. Уменьшите сумму или замените "
                            "операцию другой категорией."
                        ),
                    )
                )

        balance = money(balance + money_delta)
        fees = money(fees + fee)
        energy -= energy_cost
        time_left -= time_cost

        if balance < ZERO:
            violations.append(
                Violation(
                    reason="insufficient_balance",
                    step_id=step_id,
                    step_index=index,
                    field="amount",
                    current=str(balance),
                    allowed="0.00",
                    message=(
                        f"{_step_label(index, spec)}, поле «Сумма»: после операции и комиссии "
                        f"баланс становится {_fmt_money(balance)} — денег не хватает. "
                        "Уменьшите сумму или добавьте поступление раньше по цепочке."
                    ),
                )
            )
        if energy < 0:
            violations.append(
                Violation(
                    reason="insufficient_energy",
                    step_id=step_id,
                    step_index=index,
                    field="frequency",
                    current=str(energy),
                    allowed="0",
                    message=(
                        f"{_step_label(index, spec)}: не хватает энергии (остаток {energy}). "
                        "Уменьшите число повторов или удалите один из шагов."
                    ),
                )
            )
        if time_left < 0:
            violations.append(
                Violation(
                    reason="insufficient_time",
                    step_id=step_id,
                    step_index=index,
                    field="frequency",
                    current=str(time_left),
                    allowed="0",
                    message=(
                        f"{_step_label(index, spec)}: не хватает времени раунда "
                        f"(остаток {time_left}). Уберите шаг, ускорьте темп или откажитесь "
                        "от обслуживания в отделении."
                    ),
                )
            )
        per_step.append(
            {
                "step_id": step_id,
                "step_index": index,
                "card_code": spec.code,
                "card_version": spec.version,
                "card_title": spec.title,
                "resources_before": resources_before,
                "resources_after": {
                    "balance": str(balance),
                    "energy": energy,
                    "time": time_left,
                },
                "gross": str(gross),
                "fee": str(fee),
                "money_delta": str(money_delta),
                "energy_cost": energy_cost,
                "time_cost": time_cost,
                "balance_after": str(balance),
                "energy_after": energy,
                "time_after": time_left,
                "detail_factors": [
                    {**factor, "risk_points": str(factor["risk_points"])}
                    for factor in effects["factors"]
                ],
            }
        )

    available_steps = max(0, rules.max_actions - len(steps))
    goal_reached = outflow >= rules.target_outflow

    snapshot: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "valid": not violations,
        "resources_after": {
            "balance": str(balance),
            "energy": energy,
            "time": time_left,
            "available_steps": available_steps,
        },
        "totals": {
            "gross_inflow": str(inflow),
            "gross_outflow": str(outflow),
            "fees": str(fees),
        },
        "objective": {
            "target_outflow": str(rules.target_outflow),
            "reached": goal_reached,
        },
        "limit_usage": {
            **{key: str(value) for key, value in quota_usage.items()},
            "night_operations": night_operations,
            "anonymous_operations": anonymous_operations,
            "actions": len(steps),
        },
        "limits": [
            {
                "code": key,
                "label": QUOTA_LABELS[key],
                "kind": "money",
                "used": str(quota_usage[key]),
                "limit": str(rules.category_limits.get(key, ZERO)),
                "remaining": str(
                    max(ZERO, rules.category_limits.get(key, ZERO) - quota_usage[key])
                ),
            }
            for key in QUOTA_LABELS
            if key in rules.category_limits
        ]
        + [
            {
                "code": "night_operations",
                "label": "Ночные операции",
                "kind": "count",
                "used": str(night_operations),
                "limit": str(rules.max_night_operations),
                "remaining": str(max(0, rules.max_night_operations - night_operations)),
            },
            {
                "code": "anonymous_operations",
                "label": "Анонимные получатели",
                "kind": "count",
                "used": str(anonymous_operations),
                "limit": str(rules.max_anonymous_operations),
                "remaining": str(
                    max(0, rules.max_anonymous_operations - anonymous_operations)
                ),
            },
            {
                "code": "actions",
                "label": "Действия в раунде",
                "kind": "count",
                "used": str(len(steps)),
                "limit": str(rules.max_actions),
                "remaining": str(max(0, rules.max_actions - len(steps))),
            },
        ],
        "violations": [violation.as_dict() for violation in violations],
        "per_step": per_step,
    }
    snapshot["goal_reached"] = goal_reached
    return snapshot


def submit_blockers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Reasons a structurally valid chain still may not be submitted."""
    blockers = list(snapshot.get("violations", []))
    if not snapshot.get("per_step"):
        blockers.append(
            Violation(
                reason="scenario_empty",
                field="steps",
                current="0",
                allowed="1..",
                message=(
                    "Цепочка пуста. Добавьте хотя бы одну операцию, чтобы отправить сценарий."
                ),
            ).as_dict()
        )
    objective = snapshot.get("objective", {})
    if not objective.get("reached", False):
        target = money(objective.get("target_outflow", "0"))
        current = money(snapshot.get("totals", {}).get("gross_outflow", "0"))
        blockers.append(
            Violation(
                reason="target_outflow_not_reached",
                field="objective.target_outflow",
                current=str(current),
                allowed=str(target),
                message=(
                    f"Цель раунда не достигнута: расходный оборот {_fmt_money(current)} "
                    f"из необходимых {_fmt_money(target)}. Добавьте или увеличьте расходные "
                    "операции."
                ),
            ).as_dict()
        )
    return blockers


def specs_by_key(specs: Iterable[CardSpec]) -> dict[tuple[str, int], CardSpec]:
    return {spec.key: spec for spec in specs}
