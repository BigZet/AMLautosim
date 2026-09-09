"""Structure for the scenario engine."""

from __future__ import annotations

from collections.abc import Sequence
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

from .game_models import CardSpec, Violation, _step_label


def resolve_policy(
    card_specs: dict[tuple[str, int], CardSpec],
    game_config: dict[str, Any] | None,
    policy: RoundPolicy | None = None,
) -> RoundPolicy:
    """Resolve the explicit policy of a configured round."""
    if policy is not None:
        return policy
    return RoundPolicy.from_config(game_config, card_specs)


def validate_structure(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    policy: RoundPolicy,
) -> list[Violation]:
    """Check every step against its card version contract and round policy.

    `steps` must already have passed Pydantic validation and normalisation, so
    each entry has `step_id`, `card`, `amount`, `context` and
    `action_details` with concrete values.
    """
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

        if not policy.is_enabled((code, version)):
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
        violations.extend(
            _validate_context_fields(index, step_id, step, spec, operation)
        )
        violations.extend(
            _validate_action_details(index, step_id, step, spec, operation)
        )

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
                    index,
                    step_id,
                    spec,
                    PARAM_CHANNEL,
                    "Канал",
                    channel,
                    expected,
                    "context.channel",
                    current_label=channel_label(channel),
                    expected_label=channel_label(str(expected)),
                )
            ]
    return []


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
    for key, default in spec.context_defaults.items():
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
                            str(option["value"])
                            for option in field_spec.get("options", [])
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
