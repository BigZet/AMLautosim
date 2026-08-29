"""Structured editor for a round configuration.

Every control here maps onto one field of `schemas.round_config.GameConfigIn`,
and every one of those fields really changes what the API accepts, what the
participant sees or how the round is scored. There is no decorative setting,
and there is no raw-JSON editing: the JSON is only offered read-only, as a
diagnostic.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

QUOTA_LABELS = {
    "cash": "Наличные операции",
    "international": "Международные переводы",
    "crypto": "Криптовалюта",
    "anonymous": "Анонимные получатели",
    "high_risk_country": "Страны высокого риска",
}

RESOURCE_WEIGHT_LABELS = {
    "balance": "Баланс",
    "energy": "Энергия",
    "time": "Время",
    "trust": "Доверие",
    "fees": "Комиссии",
    "slots": "Свободные слоты",
}

#: Card attributes a round may re-tune, with the widget bounds for each.
OVERRIDES = (
    ("min_amount", "Мин. сумма", 0.0, 100_000_000.0, 1000.0),
    ("max_amount", "Макс. сумма", 0.0, 100_000_000.0, 1000.0),
    ("max_frequency", "Повторов в шаге", 1.0, 20.0, 1.0),
    ("round_frequency_limit", "Повторов за раунд", 1.0, 64.0, 1.0),
    ("energy_cost", "Энергия", 0.0, 50.0, 1.0),
    ("time_cost", "Время", 0.0, 50.0, 1.0),
    ("trust_cost", "Доверие", 0.0, 200.0, 1.0),
)

MAX_VISIBLE_PARAMS = 2


def _number(label: str, value: Any, **kwargs: Any) -> float:
    return float(st.number_input(label, value=float(value), **kwargs))


def param_label(card: dict[str, Any], param: str) -> str:
    """Human name of one declarable parameter of a card version."""
    if param == "channel":
        return "Канал"
    namespace, _, key = param.partition(".")
    source = card.get("context_fields" if namespace == "context" else "fields", [])
    for item in source:
        if item["key"] == key:
            return str(item["label"])
    return param


def declarable_params(card: dict[str, Any]) -> list[str]:
    return (
        ["channel"]
        + [f"context.{item['key']}" for item in card.get("context_fields", [])]
        + [f"action.{item['key']}" for item in card.get("fields", [])]
    )


def render_editor(
    config: dict[str, Any],
    catalog: list[dict[str, Any]],
    key_prefix: str = "cfg",
) -> dict[str, Any]:
    """Draw the whole configuration and return the edited version."""
    resources = dict(config.get("resources") or {})
    objectives = dict(config.get("objectives") or {})
    constraints = dict(config.get("constraints") or {})
    scoring = dict(config.get("scoring") or {})
    leaderboard = dict(config.get("leaderboard") or {})
    weights = dict(leaderboard.get("weights") or {})
    resource_weights = dict(leaderboard.get("resource_weights") or {})
    limits = dict(constraints.get("category_limits") or {})
    operations = {
        (str(item["code"]), int(item.get("version", 1))): dict(item)
        for item in (config.get("operations") or [])
    }

    st.markdown("#### Стартовые ресурсы")
    columns = st.columns(4)
    with columns[0]:
        initial_balance = _number(
            "Стартовый баланс, ₽",
            resources.get("initial_balance", 250000),
            min_value=1.0,
            step=10000.0,
            key=f"{key_prefix}_balance",
        )
    with columns[1]:
        initial_energy = int(
            _number(
                "Энергия",
                resources.get("initial_energy", 14),
                min_value=1.0,
                max_value=200.0,
                step=1.0,
                key=f"{key_prefix}_energy",
            )
        )
    with columns[2]:
        initial_time = int(
            _number(
                "Время",
                resources.get("initial_time", 18),
                min_value=1.0,
                max_value=200.0,
                step=1.0,
                key=f"{key_prefix}_time",
            )
        )
    with columns[3]:
        initial_trust = int(
            _number(
                "Доверие",
                resources.get("initial_trust", 100),
                min_value=1.0,
                max_value=1000.0,
                step=5.0,
                key=f"{key_prefix}_trust",
            )
        )

    st.markdown("#### Цель и ограничения раунда")
    columns = st.columns(4)
    with columns[0]:
        target_outflow = _number(
            "Цель: расходный оборот, ₽",
            objectives.get("target_outflow", 150000),
            min_value=1.0,
            step=10000.0,
            key=f"{key_prefix}_target",
        )
    with columns[1]:
        max_actions = int(
            _number(
                "Максимум операций",
                objectives.get("max_actions", 8),
                min_value=1.0,
                max_value=64.0,
                step=1.0,
                key=f"{key_prefix}_max_actions",
            )
        )
    with columns[2]:
        max_identical = int(
            _number(
                "Одинаковых подряд",
                constraints.get("max_identical_steps", 2),
                min_value=1.0,
                max_value=64.0,
                step=1.0,
                key=f"{key_prefix}_identical",
            )
        )
    with columns[3]:
        max_night = int(
            _number(
                "Ночных операций",
                constraints.get("max_night_operations", 2),
                min_value=0.0,
                max_value=64.0,
                step=1.0,
                key=f"{key_prefix}_night",
            )
        )
    max_anonymous = int(
        _number(
            "Операций на анонимного получателя",
            constraints.get("max_anonymous_operations", 2),
            min_value=0.0,
            max_value=64.0,
            step=1.0,
            key=f"{key_prefix}_anonymous",
        )
    )

    st.markdown("#### Квоты по категориям, ₽")
    quota_columns = st.columns(len(QUOTA_LABELS))
    category_limits: dict[str, str] = {}
    for column, (code, label) in zip(quota_columns, QUOTA_LABELS.items(), strict=False):
        with column:
            value = _number(
                label,
                limits.get(code, 0),
                min_value=0.0,
                step=10000.0,
                key=f"{key_prefix}_quota_{code}",
            )
            category_limits[code] = f"{value:.2f}"

    st.markdown("#### Доступные операции и видимые параметры")
    st.caption(
        "Для одной операции участник видит сумму, при необходимости число повторов "
        f"и не более {MAX_VISIBLE_PARAMS} дополнительных параметров. Остальные "
        "параметры получают серверные значения по умолчанию."
    )
    enabled_operations: list[dict[str, Any]] = []
    for card in catalog:
        key = (card["code"], card["version"])
        stored = operations.get(key)
        with st.container(border=True):
            head, freq = st.columns([3, 1])
            with head:
                enabled = st.checkbox(
                    f"{card['title']} · {card['category']}",
                    value=stored is not None,
                    key=f"{key_prefix}_op_{card['code']}",
                )
            if not enabled:
                continue
            with freq:
                show_frequency = st.checkbox(
                    "Повторы",
                    value=bool(
                        stored.get("show_frequency", card.get("show_frequency", True))
                        if stored
                        else card.get("show_frequency", True)
                    ),
                    key=f"{key_prefix}_freq_{card['code']}",
                )
            available = declarable_params(card)
            default_visible = (
                list(stored.get("visible_params", []))
                if stored
                else [item["param"] for item in card.get("visible_params", [])]
            )
            visible = st.multiselect(
                "Видимые параметры",
                available,
                default=[item for item in default_visible if item in available],
                format_func=lambda item, current=card: param_label(current, item),
                key=f"{key_prefix}_params_{card['code']}",
                max_selections=MAX_VISIBLE_PARAMS,
            )
            entry: dict[str, Any] = {
                "code": card["code"],
                "version": card["version"],
                "visible_params": visible,
                "show_frequency": show_frequency,
            }
            with st.expander("Числовые параметры операции", expanded=False):
                override_columns = st.columns(4)
                for position, (field, label, low, high, step) in enumerate(OVERRIDES):
                    with override_columns[position % 4]:
                        fallback = stored.get(field) if stored else None
                        if fallback is None:
                            fallback = card.get(
                                field,
                                (card.get("costs") or {}).get(
                                    field.replace("_cost", ""), 0
                                ),
                            )
                        value = _number(
                            label,
                            fallback,
                            min_value=low,
                            max_value=high,
                            step=step,
                            key=f"{key_prefix}_{card['code']}_{field}",
                        )
                        entry[field] = (
                            f"{value:.2f}"
                            if field in {"min_amount", "max_amount"}
                            else int(value)
                        )
            enabled_operations.append(entry)

    st.markdown("#### Скоринг и лидерборд")
    columns = st.columns(4)
    with columns[0]:
        review_threshold = _number(
            "Порог «проверить»",
            scoring.get("review_threshold", 35),
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{key_prefix}_review",
        )
    with columns[1]:
        suspicious_threshold = _number(
            "Порог «подозрительно»",
            scoring.get("suspicious_threshold", 65),
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{key_prefix}_suspicious",
        )
    with columns[2]:
        stealth_weight = _number(
            "Вес незаметности",
            weights.get("stealth", 0.60),
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key=f"{key_prefix}_w_stealth",
        )
    with columns[3]:
        st.metric("Вес ресурсов", f"{1 - stealth_weight:.2f}")

    st.caption("Веса ресурсов (в сумме 1.00)")
    weight_columns = st.columns(len(RESOURCE_WEIGHT_LABELS))
    raw_resource_weights: dict[str, float] = {}
    for column, (code, label) in zip(
        weight_columns, RESOURCE_WEIGHT_LABELS.items(), strict=False
    ):
        with column:
            raw_resource_weights[code] = _number(
                label,
                resource_weights.get(code, 0.0),
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                key=f"{key_prefix}_rw_{code}",
            )
    total_resource_weight = sum(raw_resource_weights.values())
    if abs(total_resource_weight - 1.0) > 1e-9:
        st.warning(
            f"Сумма весов ресурсов сейчас {total_resource_weight:.2f}; "
            "сервер примет конфигурацию только при сумме 1.00."
        )

    return {
        "schema_version": 3,
        "operations": enabled_operations,
        "resources": {
            "initial_balance": f"{initial_balance:.2f}",
            "initial_energy": initial_energy,
            "initial_time": initial_time,
            "initial_trust": initial_trust,
        },
        "objectives": {
            "target_outflow": f"{target_outflow:.2f}",
            "max_actions": max_actions,
        },
        "constraints": {
            "max_identical_steps": max_identical,
            "max_night_operations": max_night,
            "max_anonymous_operations": max_anonymous,
            "category_limits": category_limits,
        },
        "ruleset_version": config.get("ruleset_version", "game-rules-v2"),
        "scoring": {
            "version": scoring.get("version", "risk-rules-v2"),
            "review_threshold": f"{review_threshold:.2f}",
            "suspicious_threshold": f"{suspicious_threshold:.2f}",
        },
        "leaderboard": {
            "version": leaderboard.get("version", "leaderboard-v1"),
            "weights": {
                "stealth": f"{stealth_weight:.2f}",
                "resources": f"{1 - stealth_weight:.2f}",
            },
            "resource_weights": {
                code: f"{value:.2f}" for code, value in raw_resource_weights.items()
            },
        },
    }
