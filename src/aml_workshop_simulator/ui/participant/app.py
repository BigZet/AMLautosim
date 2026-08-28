"""Participant Streamlit application.

Every piece of state shown here comes from `/api/v1`; the UI owns no game rule
of its own. The card contract served by the API decides which channels, context
fields and action details a step may contain, so the form can never offer a
value the server would reject.
"""

from __future__ import annotations

import sys
import uuid
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.aml_workshop_simulator.ui.shared.api_client import APIClientError  # noqa: E402
from src.aml_workshop_simulator.ui.shared.session import (  # noqa: E402
    PLAY_COOKIE,
    clear_session,
    get_api_client,
    get_cookie_controller,
    reset_user_state,
    resolve_session,
    store_session,
)

st.set_page_config(
    page_title="AML Workshop Simulator",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

STYLES = """
<style>
:root {
    --aml-line: color-mix(in srgb, var(--text-color) 18%, transparent);
    --aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
    --aml-danger: #c0392b;
    --aml-ok: #1e8449;
}
.block-container { max-width: 1240px; padding-top: 1.2rem; padding-bottom: 3rem; }
[data-testid="stMetric"] {
    padding: .7rem .8rem;
    border: 1px solid var(--aml-line);
    border-radius: 6px;
    background: var(--secondary-background-color);
}
.aml-kicker { font-size: 12px; font-weight: 700; text-transform: uppercase;
    color: var(--primary-color); margin-bottom: .3rem; }
.aml-title { font-size: 30px; font-weight: 800; line-height: 1.2; margin: 0 0 .3rem; }
.aml-subtitle { color: var(--aml-muted); font-size: 15px; margin: 0 0 1rem; max-width: 820px; }
.aml-violation {
    border-left: 4px solid var(--aml-danger);
    background: color-mix(in srgb, var(--aml-danger) 10%, var(--background-color));
    padding: .6rem .8rem; border-radius: 4px; margin: .35rem 0; font-size: 14px;
}
.aml-violation strong { color: var(--aml-danger); }
.aml-ok-box {
    border-left: 4px solid var(--aml-ok);
    background: color-mix(in srgb, var(--aml-ok) 10%, var(--background-color));
    padding: .6rem .8rem; border-radius: 4px; margin: .35rem 0; font-size: 14px;
}
.aml-step-meta { color: var(--aml-muted); font-size: 13px; }
.aml-status-badge {
    display: inline-block; padding: .15rem .55rem; border-radius: 999px;
    border: 1px solid var(--aml-line); font-size: 12px; font-weight: 600;
}
table.aml-board { width: 100%; border-collapse: collapse; font-size: 14px; }
table.aml-board th, table.aml-board td {
    border-bottom: 1px solid var(--aml-line); padding: .45rem .5rem; text-align: left;
}
.aml-scroll { overflow-x: auto; }
</style>
"""
st.markdown(STYLES, unsafe_allow_html=True)

STATUS_LABELS = {
    "draft": "Черновик",
    "submitted": "Отправлен",
    "scored": "Оценен",
    "none": "Не создан",
}
RISK_LABELS = {
    "normal": "Норма",
    "review": "Требует проверки",
    "suspicious": "Подозрительно",
}


# --------------------------------------------------------------------------
# State helpers
# --------------------------------------------------------------------------


def init_state() -> None:
    defaults: dict[str, Any] = {
        "draft_steps": [],
        "server_revision": 0,
        "server_scenario": None,
        "field_errors": {},
        "chain_violations": [],
        "flash": None,
        "editing_step_id": None,
        "pending_command": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(f'<div class="aml-kicker">{escape(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="aml-title">{escape(title)}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="aml-subtitle">{escape(subtitle)}</div>', unsafe_allow_html=True
    )


def marker(testid: str, value: Any) -> None:
    """Hidden, stable DOM anchor for browser assertions."""
    st.markdown(
        f'<span data-testid="{escape(testid)}" style="display:none">{escape(str(value))}</span>',
        unsafe_allow_html=True,
    )


def show_flash() -> None:
    flash = st.session_state.get("flash")
    if not flash:
        return
    kind, message = flash
    container = {"success": st.success, "error": st.error, "warning": st.warning}.get(
        kind, st.info
    )
    container(message)
    marker(f"flash-{kind}", message)
    st.session_state["flash"] = None


def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def apply_error(error: APIClientError) -> None:
    """Map an error envelope onto per-step field errors and a flash message."""
    violations = (error.details or {}).get("violations", []) if error.details else []
    field_errors: dict[str, str] = {}
    chain: list[dict[str, Any]] = []
    for violation in violations:
        step_id = violation.get("step_id")
        field = violation.get("field")
        if step_id and field:
            field_errors[f"{step_id}::{field}"] = violation.get("message", "")
        chain.append(violation)
    st.session_state["field_errors"] = field_errors
    st.session_state["chain_violations"] = chain
    set_flash("error", error.message)


def store_scenario(scenario: dict[str, Any]) -> None:
    st.session_state["server_scenario"] = scenario
    st.session_state["server_revision"] = scenario.get("revision", 0)
    st.session_state["draft_steps"] = [dict(step) for step in scenario.get("steps", [])]
    resources = scenario.get("resources") or {}
    violations = resources.get("violations", [])
    st.session_state["chain_violations"] = violations
    st.session_state["field_errors"] = {
        f"{item['step_id']}::{item['field']}": item.get("message", "")
        for item in violations
        if item.get("step_id") and item.get("field")
    }


def load_scenario(client: Any, round_id: int, session_id: str) -> None:
    scenario = client.get_scenario(round_id, session_id)
    if scenario:
        store_scenario(scenario)
    else:
        st.session_state["server_scenario"] = None
        st.session_state["server_revision"] = 0
        st.session_state["draft_steps"] = []
        st.session_state["chain_violations"] = []
        st.session_state["field_errors"] = {}
    st.session_state["loaded_for"] = (round_id, session_id)


# --------------------------------------------------------------------------
# Server commands
# --------------------------------------------------------------------------


def save_draft(
    client: Any, round_id: int, session_id: str, *, quiet: bool = False
) -> dict[str, Any] | None:
    """PUT the local draft; returns the canonical scenario or None on error."""
    if st.session_state.get("pending_command"):
        return None
    st.session_state["pending_command"] = "save"
    try:
        scenario = client.put_scenario(
            round_id,
            st.session_state["draft_steps"],
            st.session_state["server_revision"],
            session_id,
            client_mutation_id=str(uuid.uuid4()),
        )
    except APIClientError as error:
        apply_error(error)
        return None
    finally:
        st.session_state["pending_command"] = None

    store_scenario(scenario)
    if not quiet:
        resources = scenario.get("resources") or {}
        if resources.get("valid"):
            set_flash(
                "success",
                f"Черновик сохранен на сервере (ревизия {scenario['revision']}).",
            )
        else:
            set_flash(
                "warning",
                f"Черновик сохранен (ревизия {scenario['revision']}), "
                "но содержит нарушения правил — отправка недоступна.",
            )
    return scenario


def submit_scenario(client: Any, round_id: int, session_id: str) -> None:
    if st.session_state.get("pending_command"):
        return
    saved = save_draft(client, round_id, session_id, quiet=True)
    if saved is None:
        return
    st.session_state["pending_command"] = "submit"
    try:
        scenario = client.submit_scenario(round_id, saved["revision"], session_id)
    except APIClientError as error:
        apply_error(error)
        return
    finally:
        st.session_state["pending_command"] = None
    store_scenario(scenario)
    set_flash("success", "Сценарий отправлен и ожидает скоринга организатора.")


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


def login_screen(client: Any, controller: Any) -> None:
    header(
        "AML Workshop Simulator",
        "Вход в симулятор",
        "Войдите или создайте игровой профиль, чтобы собрать цепочку операций.",
    )
    marker("auth-state", "anonymous")
    show_flash()

    tab_login, tab_register = st.tabs(["Вход", "Регистрация"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Пароль", type="password", key="login_password")
            submitted = st.form_submit_button(
                "Войти", use_container_width=True, type="primary"
            )
        if submitted:
            try:
                created = client.login(email.strip(), password, audience="play")
            except APIClientError as error:
                set_flash("error", error.message)
                st.rerun()
                return
            st.session_state["session_id"] = created["session_id"]
            st.session_state["user"] = created["user"]
            store_session(
                controller, PLAY_COOKIE, created["session_id"], created.get("expires_at")
            )
            st.rerun()

    with tab_register:
        with st.form("register_form"):
            display_name = st.text_input("Игровой псевдоним", key="register_name")
            reg_email = st.text_input("Email", key="register_email")
            reg_password = st.text_input(
                "Пароль (не менее 10 символов)", type="password", key="register_password"
            )
            registered = st.form_submit_button("Зарегистрироваться", use_container_width=True)
        if registered:
            try:
                client.register(reg_email.strip(), display_name.strip(), reg_password)
            except APIClientError as error:
                set_flash("error", error.message)
                st.rerun()
                return
            set_flash("success", "Регистрация выполнена. Теперь войдите на вкладке «Вход».")
            st.rerun()


# --------------------------------------------------------------------------
# Scenario builder
# --------------------------------------------------------------------------


def default_step(card: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {
        "country_risk": "low",
        "recipient_type": "known_counterparty",
        "time_of_day": "day",
        "velocity": "normal",
        "channel": card["channels"][0],
        "has_documents": True,
    }
    for field in card.get("context_fields", []):
        context[field["key"]] = field["default"]
    return {
        "step_id": str(uuid.uuid4()),
        "card": {"id": card["id"], "code": card["code"], "version": card["version"]},
        "amount": f"{float(card['min_amount']):.2f}",
        "frequency": 1,
        "context": context,
        "action_details": {
            field["key"]: field["default"] for field in card.get("fields", [])
        },
    }


def render_step_form(
    card: dict[str, Any],
    step: dict[str, Any],
    key_prefix: str,
) -> dict[str, Any]:
    """Render every editable field of one step and return the updated step."""
    context = dict(step["context"])
    details = dict(step["action_details"])

    amount_col, frequency_col, channel_col = st.columns([1.3, 0.7, 1.2])
    with amount_col:
        amount = st.number_input(
            f"Сумма, ₽ (от {float(card['min_amount']):,.0f} до {float(card['max_amount']):,.0f})".replace(
                ",", " "
            ),
            min_value=0.0,
            value=float(step["amount"]),
            step=1000.0,
            format="%.2f",
            key=f"{key_prefix}_amount",
        )
    with frequency_col:
        frequency = st.number_input(
            f"Повторов (до {card['max_frequency']})",
            min_value=1,
            max_value=20,
            value=int(step["frequency"]),
            step=1,
            key=f"{key_prefix}_frequency",
        )
    with channel_col:
        channels: list[str] = card["channels"]
        labels: dict[str, str] = card.get("channel_labels", {})
        current = context.get("channel", channels[0])
        index = channels.index(current) if current in channels else 0
        channel = st.selectbox(
            "Канал",
            channels,
            index=index,
            format_func=lambda value: labels.get(value, value),
            key=f"{key_prefix}_channel",
        )
    context["channel"] = channel

    context_fields = card.get("context_fields", [])
    if context_fields:
        st.caption("Контекст операции")
        columns = st.columns(min(3, len(context_fields)))
        for position, field in enumerate(context_fields):
            column = columns[position % len(columns)]
            with column:
                key = field["key"]
                widget_key = f"{key_prefix}_ctx_{key}"
                if field.get("kind") == "toggle":
                    context[key] = st.toggle(
                        field["label"],
                        value=bool(context.get(key, field["default"])),
                        key=widget_key,
                    )
                else:
                    options = [option["value"] for option in field.get("options", [])]
                    option_labels = {
                        option["value"]: option["label"]
                        for option in field.get("options", [])
                    }
                    value = context.get(key, field["default"])
                    context[key] = st.selectbox(
                        field["label"],
                        options,
                        index=options.index(value) if value in options else 0,
                        format_func=lambda item, mapping=option_labels: mapping.get(
                            item, item
                        ),
                        key=widget_key,
                    )

    action_fields = card.get("fields", [])
    if action_fields:
        st.caption("Параметры операции")
        columns = st.columns(min(3, len(action_fields)))
        for position, field in enumerate(action_fields):
            column = columns[position % len(columns)]
            with column:
                key = field["key"]
                options = [option["value"] for option in field.get("options", [])]
                option_labels = {
                    option["value"]: option["label"] for option in field.get("options", [])
                }
                value = details.get(key, field["default"])
                details[key] = st.selectbox(
                    field["label"],
                    options,
                    index=options.index(value) if value in options else 0,
                    format_func=lambda item, mapping=option_labels: mapping.get(item, item),
                    key=f"{key_prefix}_detail_{key}",
                )

    return {
        **step,
        "amount": f"{float(amount):.2f}",
        "frequency": int(frequency),
        "context": context,
        "action_details": details,
    }


def render_builder(cards: dict[str, dict[str, Any]]) -> None:
    st.subheader("Новая операция")
    codes = list(cards)
    selected = st.selectbox(
        "Тип операции",
        codes,
        format_func=lambda code: f"{cards[code]['title']} · {cards[code]['category']}",
        key="builder_card",
    )
    card = cards[selected]
    st.caption(card.get("description", ""))
    marker("builder-channels", ",".join(card["channels"]))

    draft_key = f"builder_step_{selected}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = default_step(card)
    step = render_step_form(card, st.session_state[draft_key], f"builder_{selected}")
    st.session_state[draft_key] = step

    limit_reached = len(st.session_state["draft_steps"]) >= 8
    if st.button(
        "Добавить в цепочку",
        type="primary",
        use_container_width=True,
        key="add_step",
        disabled=limit_reached,
    ):
        new_step = {**step, "step_id": str(uuid.uuid4())}
        st.session_state["draft_steps"].append(new_step)
        st.session_state[draft_key] = default_step(card)
        st.rerun()
    if limit_reached:
        st.warning("Достигнут лимит действий раунда: удалите шаг, чтобы добавить новый.")


def render_chain(
    cards_by_key: dict[tuple[str, int], dict[str, Any]],
    editable: bool,
) -> None:
    steps: list[dict[str, Any]] = st.session_state["draft_steps"]
    st.subheader(f"Цепочка операций ({len(steps)})")
    marker("chain-length", len(steps))
    if not steps:
        st.info("Цепочка пуста. Настройте операцию слева и добавьте её в цепочку.")
        return

    per_step = {
        item["step_id"]: item
        for item in ((st.session_state.get("server_scenario") or {}).get("resources") or {}).get(
            "per_step", []
        )
    }
    field_errors: dict[str, str] = st.session_state["field_errors"]
    move: tuple[int, int] | None = None
    delete_index: int | None = None
    duplicate_index: int | None = None

    for index, step in enumerate(steps):
        card = cards_by_key.get((step["card"]["code"], step["card"]["version"]))
        title = card["title"] if card else step["card"]["code"]
        step_id = step["step_id"]
        step_errors = {
            key.split("::", 1)[1]: value
            for key, value in field_errors.items()
            if key.startswith(f"{step_id}::")
        }
        with st.container(border=True):
            st.markdown(
                f'<div data-testid="step-card-{escape(step_id)}">'
                f"<strong>{index + 1}. {escape(title)}</strong></div>",
                unsafe_allow_html=True,
            )
            impact = per_step.get(step_id, {})
            channel_label = (card or {}).get("channel_labels", {}).get(
                step["context"]["channel"], step["context"]["channel"]
            )
            st.markdown(
                f'<div class="aml-step-meta">{money(step["amount"])} × {step["frequency"]}'
                f' · канал: <span data-testid="step-channel-{escape(step_id)}">'
                f"{escape(channel_label)}</span>"
                + (
                    f' · баланс после: {money(impact.get("balance_after"))}'
                    if impact
                    else ""
                )
                + "</div>",
                unsafe_allow_html=True,
            )
            for field, message in step_errors.items():
                st.markdown(
                    f'<div class="aml-violation" data-testid="step-error-{escape(step_id)}-'
                    f'{escape(field)}"><strong>{escape(field)}</strong>: {escape(message)}</div>',
                    unsafe_allow_html=True,
                )

            if editable and card is not None:
                with st.expander("Изменить шаг", expanded=st.session_state["editing_step_id"] == step_id):
                    updated = render_step_form(card, step, f"edit_{step_id}")
                    if updated != step:
                        steps[index] = updated
                col_up, col_down, col_copy, col_delete = st.columns(4)
                with col_up:
                    if st.button(
                        "Вверх", key=f"up_{step_id}", disabled=index == 0,
                        use_container_width=True,
                    ):
                        move = (index, index - 1)
                with col_down:
                    if st.button(
                        "Вниз", key=f"down_{step_id}",
                        disabled=index == len(steps) - 1, use_container_width=True,
                    ):
                        move = (index, index + 1)
                with col_copy:
                    if st.button(
                        "Дублировать", key=f"copy_{step_id}", use_container_width=True
                    ):
                        duplicate_index = index
                with col_delete:
                    if st.button(
                        "Удалить", key=f"delete_{step_id}", use_container_width=True
                    ):
                        delete_index = index

    if move is not None:
        source, target = move
        steps[source], steps[target] = steps[target], steps[source]
        st.rerun()
    if duplicate_index is not None:
        clone = {
            **steps[duplicate_index],
            "step_id": str(uuid.uuid4()),
            "context": dict(steps[duplicate_index]["context"]),
            "action_details": dict(steps[duplicate_index]["action_details"]),
        }
        steps.insert(duplicate_index + 1, clone)
        st.rerun()
    if delete_index is not None:
        steps.pop(delete_index)
        st.rerun()


def render_resources(scenario: dict[str, Any] | None) -> None:
    resources = (scenario or {}).get("resources") or {}
    after = resources.get("resources_after", {})
    totals = resources.get("totals", {})
    objective = resources.get("objective", {})

    columns = st.columns(5)
    values = (
        ("Баланс", money(after.get("balance", 0)), "balance"),
        ("Энергия", after.get("energy", 0), "energy"),
        ("Время", after.get("time", 0), "time"),
        ("Доверие", after.get("trust", 0), "trust"),
        ("Слоты", after.get("slots", 0), "slots"),
    )
    for column, (label, value, testid) in zip(columns, values, strict=False):
        with column:
            st.metric(label, value)
            marker(f"resource-{testid}", value)

    reached = bool(objective.get("reached"))
    marker("objective-reached", "true" if reached else "false")
    marker("resources-valid", "true" if resources.get("valid") else "false")
    st.caption(
        f"Расходный оборот {money(totals.get('gross_outflow', 0))} из "
        f"{money(objective.get('target_outflow', 0))} · комиссии "
        f"{money(totals.get('fees', 0))}"
    )


def render_violations() -> None:
    violations = st.session_state.get("chain_violations") or []
    marker("violation-count", len(violations))
    if not violations:
        st.markdown(
            '<div class="aml-ok-box" data-testid="no-violations">'
            "Нарушений правил раунда нет.</div>",
            unsafe_allow_html=True,
        )
        return
    st.markdown("**Нарушения правил раунда**")
    for violation in violations:
        st.markdown(
            f'<div class="aml-violation" data-testid="violation-{escape(violation.get("reason", ""))}">'
            f"{escape(violation.get('message', ''))}</div>",
            unsafe_allow_html=True,
        )


def page_scenario() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    active_round = client.get_active_round()
    if not active_round:
        header("Раунд", "Ожидание раунда", "Организатор ещё не активировал раунд.")
        marker("round-status", "none")
        return

    round_id = active_round["id"]
    if st.session_state.get("loaded_for") != (round_id, session_id):
        load_scenario(client, round_id, session_id)

    cards_list = client.get_round_cards(round_id)
    cards = {card["code"]: card for card in cards_list}
    cards_by_key = {(card["code"], card["version"]): card for card in cards_list}

    scenario = st.session_state.get("server_scenario")
    status = (scenario or {}).get("status", "none")
    editable = status in {"draft", "none"} and active_round["status"] == "active"

    header(
        f"Раунд #{round_id}",
        "Конструктор сценария",
        "Соберите цепочку операций, сохраните черновик и отправьте её на скоринг.",
    )
    marker("scenario-status", status)
    marker("scenario-revision", (scenario or {}).get("revision", 0))
    marker("round-status", active_round["status"])
    st.markdown(
        f'<span class="aml-status-badge" data-testid="status-badge">'
        f"Статус: {escape(STATUS_LABELS.get(status, status))}"
        f"{' · ревизия ' + str(scenario['revision']) if scenario else ''}</span>",
        unsafe_allow_html=True,
    )
    show_flash()
    render_resources(scenario)
    render_violations()
    st.divider()

    if not editable:
        st.info(
            "Сценарий зафиксирован сервером. Изменение доступно только пока раунд "
            "активен и сценарий находится в черновике."
        )
        render_chain(cards_by_key, editable=False)
        return

    builder_column, chain_column = st.columns([1.0, 1.1], gap="large")
    with builder_column:
        render_builder(cards)
    with chain_column:
        render_chain(cards_by_key, editable=True)

        st.divider()
        resources = (scenario or {}).get("resources") or {}
        synchronized = st.session_state["draft_steps"] == (scenario or {}).get("steps", [])
        can_submit = (
            bool(scenario)
            and synchronized
            and bool(resources.get("valid"))
            and bool((resources.get("objective") or {}).get("reached"))
        )
        marker("submit-enabled", "true" if can_submit else "false")

        save_column, submit_column = st.columns(2)
        with save_column:
            if st.button(
                "Сохранить черновик",
                key="save_draft",
                use_container_width=True,
                disabled=bool(st.session_state.get("pending_command")),
            ):
                save_draft(client, round_id, session_id)
                st.rerun()
        with submit_column:
            if st.button(
                "Отправить сценарий",
                key="submit_scenario",
                type="primary",
                use_container_width=True,
                disabled=not can_submit or bool(st.session_state.get("pending_command")),
            ):
                submit_scenario(client, round_id, session_id)
                st.rerun()
        if not can_submit:
            st.caption(
                "Отправка доступна, когда сохранённая на сервере цепочка не содержит "
                "нарушений и достигает цели раунда."
            )


def page_result() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header("Результат", "Оценка учебной модели", "Разбор факторов и ресурсов.")

    rounds = client.get_my_rounds(session_id).get("rows", [])
    if not rounds:
        st.info("Пока нет раундов с вашим сценарием.")
        marker("result-state", "empty")
        return

    options = {f"#{row['id']} · {row['title']}": row for row in rounds}
    chosen = st.selectbox("Раунд", list(options), key="result_round")
    row = options[chosen]
    result = client.get_result(row["id"], session_id)
    if not result:
        st.info(
            "Результат появится после запуска общего скоринга организатором. "
            f"Текущий статус сценария: {STATUS_LABELS.get(row.get('scenario_status') or 'none')}."
        )
        marker("result-state", "pending")
        return

    marker("result-state", "ready")
    base = result["base"]
    board = result["leaderboard"]
    columns = st.columns(4)
    columns[0].metric("Игровой балл", board["effective_game_score"])
    columns[1].metric("Риск", base["risk_score"])
    columns[2].metric("Незаметность", base["stealth_score"])
    columns[3].metric("Ресурсы", base["resource_score"])
    marker("result-game-score", board["effective_game_score"])
    marker("result-risk-label", base["risk_label"])
    st.markdown(
        f'<span class="aml-status-badge" data-testid="result-label">'
        f"Решение модели: {escape(RISK_LABELS.get(base['risk_label'], base['risk_label']))}"
        "</span>",
        unsafe_allow_html=True,
    )

    explanation = result.get("explanation") or {}
    risk_tab, protective_tab = st.tabs(["Факторы риска", "Защитные факторы"])
    with risk_tab:
        for factor in explanation.get("top_risk_factors", []):
            st.markdown(
                f"**+{factor['points']}** · {escape(factor['description'])}",
                unsafe_allow_html=True,
            )
    with protective_tab:
        for factor in explanation.get("protective_factors", []):
            st.markdown(
                f"**{factor['points']}** · {escape(factor['description'])}",
                unsafe_allow_html=True,
            )
    st.caption(explanation.get("disclaimer", ""))


def page_leaderboard() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header("Лидерборд", "Итоги раунда", "Обезличенный рейтинг участников.")

    rounds = client.get_my_rounds(session_id).get("rows", [])
    if not rounds:
        st.info("Раундов пока нет.")
        return
    options = {f"#{row['id']} · {row['title']}": row for row in rounds}
    chosen = st.selectbox("Раунд", list(options), key="board_round")
    board = client.get_leaderboard(options[chosen]["id"], session_id)
    rows = board.get("rows", [])
    marker("leaderboard-rows", len(rows))
    if not rows:
        st.info("Лидерборд появится после завершения раунда.")
        return
    body = "".join(
        "<tr>"
        f"<td>{row['rank']}</td>"
        f"<td>{escape(row['display_name'])}</td>"
        f"<td>{row['game_score']}</td>"
        f"<td>{row['stealth_score']}</td>"
        f"<td>{row['resource_score']}</td>"
        f"<td>{escape(RISK_LABELS.get(row['risk_label'], row['risk_label']))}</td>"
        "</tr>"
        for row in rows
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-board" data-testid="leaderboard-table">'
        "<thead><tr><th>Место</th><th>Участник</th><th>Балл</th><th>Незаметность</th>"
        f"<th>Ресурсы</th><th>Оценка</th></tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    init_state()
    client = get_api_client()
    controller = get_cookie_controller("aml_play_cookies")
    session = resolve_session(controller, PLAY_COOKIE, client)

    if session.pending:
        st.info("Восстанавливаем сессию…")
        marker("auth-state", "pending")
        st.stop()

    if not session.authenticated:
        login_screen(client, controller)
        st.stop()

    user = session.user or {}
    with st.sidebar:
        st.markdown("### AML Workshop Simulator")
        st.markdown(
            f'<div data-testid="current-user">{escape(str(user.get("display_name", "")))}</div>',
            unsafe_allow_html=True,
        )
        marker("auth-state", "authenticated")
        if st.button("Выйти", key="logout", use_container_width=True):
            try:
                client.logout(st.session_state["session_id"])
            except APIClientError:
                st.warning("Сервер не подтвердил выход, локальная сессия очищена.")
            clear_session(controller, PLAY_COOKIE)
            reset_user_state()
            st.session_state.pop("loaded_for", None)
            st.rerun()

    navigation = st.navigation(
        [
            st.Page(page_scenario, title="Конструктор", url_path="scenario", default=True),
            st.Page(page_result, title="Результат", url_path="result"),
            st.Page(page_leaderboard, title="Лидерборд", url_path="leaderboard"),
        ],
        position="sidebar",
    )
    navigation.run()


main()
