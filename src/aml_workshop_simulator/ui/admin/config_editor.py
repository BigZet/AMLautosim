"""Structured editor for a round configuration.

Every control here maps onto one field of `schemas.round_config.GameConfigIn`,
and every one of those fields really changes what the API accepts, what the
participant sees or how the round is scored. There is no decorative setting,
and there is no raw-JSON editing: the JSON is only offered read-only, as a
diagnostic.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from typing import Any

import streamlit as st

from src.aml_workshop_simulator.core.game_config import (
    LIMITS,
    base_game_config,
    load_config,
)
from src.aml_workshop_simulator.domain.round_policy import MAX_VISIBLE_PARAMS
from src.aml_workshop_simulator.domain.rules import QUOTA_LABELS
from src.aml_workshop_simulator.schemas.round_config import CONFIG_SCHEMA_VERSION

RESOURCE_WEIGHT_LABELS = {
    "balance": "Баланс",
    "energy": "Энергия",
    "time": "Время",
    "fees": "Комиссии",
    "available_steps": "Доступные шаги",
}

OVERRIDES = (
    ("min_amount", "Мин. сумма", 0.01, float(LIMITS["max_balance"]), 1000.0),
    ("max_amount", "Макс. сумма", 0.01, float(LIMITS["max_balance"]), 1000.0),
    ("max_frequency", "Повторов в шаге", 1.0, float(LIMITS["max_frequency"]), 1.0),
    (
        "round_frequency_limit",
        "Повторов за раунд",
        1.0,
        float(LIMITS["max_actions"]),
        1.0,
    ),
    ("energy_cost", "Энергия", 0.0, float(LIMITS["max_operation_cost"]), 1.0),
    ("time_cost", "Время", 0.0, float(LIMITS["max_operation_cost"]), 1.0),
    ("fee_rate", "Комиссия (доля, 0.01 = 1%)", 0.0, 1.0, 0.000001),
    ("risk_weight", "Базовый риск", 0.0, 100.0, 0.01),
)


def _numeric_tree(values: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Edit all engine coefficients without duplicating their defaults."""
    edited = {}
    labels = load_config("editor_labels.json")
    for key, value in values.items():
        label = labels.get(key, key)
        if isinstance(value, dict):
            with st.expander(label, expanded=False):
                edited[key] = _numeric_tree(value, f"{prefix}_{key}")
        elif isinstance(value, int):
            edited[key] = st.number_input(
                label, value=value, step=1, key=f"{prefix}_{key}"
            )
        else:
            # Decimal text avoids silently rounding a coefficient to widget precision.
            edited[key] = st.text_input(label, value=str(value), key=f"{prefix}_{key}")
    return edited


def _pinned_defaults(card: dict, stored: dict, visible: list[str], prefix: str) -> dict:
    defaults = {}
    fields = {
        "channel": {
            "kind": "select",
            "default": card["channels"][0],
            "options": [
                {"value": c, "label": card.get("channel_labels", {}).get(c, c)}
                for c in card["channels"]
            ],
        }
    }
    fields.update({f"context.{f['key']}": f for f in card.get("context_fields", [])})
    fields.update({f"action.{f['key']}": f for f in card.get("fields", [])})
    for param, field in fields.items():
        if param in visible:
            continue
        value = stored.get("defaults", {}).get(param, field["default"])
        label = param_label(card, param)
        if field["kind"] == "toggle":
            defaults[param] = st.checkbox(label, value=value, key=f"{prefix}_{param}")
        else:
            options = [o["value"] for o in field["options"]]
            labels = {o["value"]: o["label"] for o in field["options"]}
            defaults[param] = st.selectbox(
                label,
                options,
                index=options.index(value),
                format_func=labels.get,
                key=f"{prefix}_{param}",
            )
    return defaults


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
    config = deepcopy(config)
    if config.get("card_snapshots"):
        # Show the same frozen catalog the server uses for this existing round.
        from src.aml_workshop_simulator.api.routers.rounds import card_out
        from src.aml_workshop_simulator.services.configuration import snapshot_specs

        frozen = {
            key: card_out(spec).model_dump()
            for key, spec in snapshot_specs(config).items()
        }
        catalog = [frozen.pop((c["code"], c["version"]), c) for c in catalog] + list(
            frozen.values()
        )
    base = base_game_config()
    # Streamlit retains widget values by key. Clear only this editor's controls
    # when the source preset/revision changes, preserving stable UI selectors.
    digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode()
    ).hexdigest()
    digest_key, owned_key = f"_cfg_digest_{key_prefix}", f"_cfg_owned_{key_prefix}"
    owned = set(st.session_state.get(owned_key, []))
    if st.session_state.get(digest_key) != digest:
        for key in owned:
            st.session_state.pop(key, None)
        st.session_state[digest_key] = digest
    existing_keys = set(st.session_state)
    resources = {**base["resources"], **config.get("resources", {})}
    objectives = {**base["objectives"], **config.get("objectives", {})}
    constraints = {**base["constraints"], **config.get("constraints", {})}
    scoring = {**base["scoring"], **config.get("scoring", {})}
    leaderboard = {**base["leaderboard"], **config.get("leaderboard", {})}
    weights = dict(leaderboard.get("weights") or {})
    resource_weights = dict(leaderboard.get("resource_weights") or {})
    limits = dict(constraints.get("category_limits") or {})
    operations = {
        (str(item["code"]), int(item.get("version", 1))): dict(item)
        for item in (config.get("operations") or [])
    }

    st.markdown("#### Стартовые ресурсы")
    columns = st.columns(3)
    with columns[0]:
        initial_balance = _number(
            "Стартовый баланс, ₽",
            resources["initial_balance"],
            min_value=0.01,
            max_value=float(LIMITS["max_balance"]),
            step=10000.0,
            key=f"{key_prefix}_balance",
        )
    with columns[1]:
        initial_energy = int(
            _number(
                "Энергия",
                resources["initial_energy"],
                min_value=1.0,
                max_value=float(LIMITS["max_resource"]),
                step=1.0,
                key=f"{key_prefix}_energy",
            )
        )
    with columns[2]:
        initial_time = int(
            _number(
                "Время",
                resources["initial_time"],
                min_value=1.0,
                max_value=float(LIMITS["max_resource"]),
                step=1.0,
                key=f"{key_prefix}_time",
            )
        )
    st.markdown("#### Цель и ограничения раунда")
    columns = st.columns(4)
    with columns[0]:
        target_outflow = _number(
            "Цель: расходный оборот, ₽",
            objectives["target_outflow"],
            min_value=0.01,
            max_value=float(LIMITS["max_balance"]),
            step=10000.0,
            key=f"{key_prefix}_target",
        )
    with columns[1]:
        max_actions = int(
            _number(
                "Максимум операций",
                objectives["max_actions"],
                min_value=1.0,
                max_value=float(LIMITS["max_actions"]),
                step=1.0,
                key=f"{key_prefix}_max_actions",
            )
        )
    with columns[2]:
        max_identical = int(
            _number(
                "Одинаковых подряд",
                constraints["max_identical_steps"],
                min_value=1.0,
                max_value=float(LIMITS["max_actions"]),
                step=1.0,
                key=f"{key_prefix}_identical",
            )
        )
    with columns[3]:
        max_night = int(
            _number(
                "Ночных операций",
                constraints["max_night_operations"],
                min_value=0.0,
                max_value=float(LIMITS["max_actions"]),
                step=1.0,
                key=f"{key_prefix}_night",
            )
        )
    max_anonymous = int(
        _number(
            "Операций на анонимного получателя",
            constraints["max_anonymous_operations"],
            min_value=0.0,
            max_value=float(LIMITS["max_actions"]),
            step=1.0,
            key=f"{key_prefix}_anonymous",
        )
    )

    st.markdown("#### Квоты по категориям, ₽")
    quota_columns = st.columns(len(QUOTA_LABELS))
    category_limits: dict[str, str] = {}
    for column, (code, label) in zip(quota_columns, QUOTA_LABELS.items(), strict=False):
        with column:
            enabled = st.checkbox(
                f"Ограничить: {label}",
                value=code in limits,
                key=f"{key_prefix}_quota_enabled_{code}",
            )
            if not enabled:
                continue
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
    legacy = not operations and bool(config.get("card_versions"))
    if legacy:
        st.info(
            "Сохранён старый режим: все параметры карточек доступны. Список карточек не изменяется."
        )
    for card in [] if legacy else catalog:
        key = (card["code"], card["version"])
        stored = operations.get(key)
        operation_prefix = f"{key_prefix}_{card['code']}_v{card['version']}"
        with st.container(border=True):
            head, freq = st.columns([3, 1])
            with head:
                enabled = st.checkbox(
                    f"{card['title']} · {card['category']}",
                    value=stored is not None,
                    key=f"{operation_prefix}_enabled",
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
                    key=f"{operation_prefix}_frequency",
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
                key=f"{operation_prefix}_params",
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
                            format="%.6f" if field == "fee_rate" else None,
                            key=f"{operation_prefix}_{field}",
                        )
                        entry[field] = (
                            f"{value:.2f}"
                            if field in {"min_amount", "max_amount", "risk_weight"}
                            else (f"{value:.6f}" if field == "fee_rate" else int(value))
                        )
            with st.expander("Значения скрытых параметров", expanded=False):
                entry["defaults"] = _pinned_defaults(
                    card, stored or {}, visible, operation_prefix
                )
            enabled_operations.append(entry)

    st.markdown("#### Скоринг и лидерборд")
    columns = st.columns(4)
    with columns[0]:
        review_threshold = _number(
            "Порог «проверить»",
            scoring["review_threshold"],
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{key_prefix}_review",
        )
    with columns[1]:
        suspicious_threshold = _number(
            "Порог «подозрительно»",
            scoring["suspicious_threshold"],
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=f"{key_prefix}_suspicious",
        )
    with columns[2]:
        stealth_weight = _number(
            "Вес незаметности",
            weights["stealth"],
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key=f"{key_prefix}_w_stealth",
        )
    with columns[3]:
        st.metric("Вес ресурсов", str(Decimal("1") - Decimal(str(stealth_weight))))

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

    with st.expander("Надбавки к стоимости операций", expanded=False):
        resource_rules = _numeric_tree(
            config.get("resource_rules", base["resource_rules"]), f"{key_prefix}_costs"
        )
    with st.expander("Коэффициенты модели риска", expanded=False):
        risk_rules = _numeric_tree(scoring["rules"], f"{key_prefix}_risk")

    st.session_state[owned_key] = sorted(
        owned
        | {
            key
            for key in st.session_state
            if key.startswith(f"{key_prefix}_") and key not in existing_keys
        }
    )
    return {
        **({"card_versions": config["card_versions"]} if legacy else {}),
        "schema_version": CONFIG_SCHEMA_VERSION,
        "resource_rules": resource_rules,
        "operations": enabled_operations,
        "resources": {
            "initial_balance": f"{initial_balance:.2f}",
            "initial_energy": initial_energy,
            "initial_time": initial_time,
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
        "ruleset_version": config.get("ruleset_version", base["ruleset_version"]),
        "scoring": {
            "version": scoring["version"],
            "rules": risk_rules,
            "review_threshold": f"{review_threshold:.2f}",
            "suspicious_threshold": f"{suspicious_threshold:.2f}",
        },
        "leaderboard": {
            "version": leaderboard["version"],
            "weights": {
                "stealth": str(Decimal(str(stealth_weight))),
                "resources": str(Decimal("1") - Decimal(str(stealth_weight))),
            },
            "resource_weights": {
                code: str(value) for code, value in raw_resource_weights.items()
            },
        },
    }
