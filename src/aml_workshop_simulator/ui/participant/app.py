"""Participant Streamlit application.

Every piece of state shown here comes from `/api/v1`; the UI owns no game rule
of its own. The card contract served by the API decides which parameters a step
may contain, and the resource numbers are recomputed by the server through
`POST /rounds/{id}/scenario/preview` after **every** change to the chain — add,
edit, delete, reorder, clear, switch version, restore — long before anything is
saved. There is therefore no second implementation of the rules that could
drift away from the canonical one.
"""

from __future__ import annotations

import json
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
    apply_pending_cookie_command,
    consume_hydration_flag,
    get_api_client,
    get_cookie_controller,
    queue_cookie_clear,
    queue_cookie_set,
    reset_user_state,
    resolve_session,
)

st.set_page_config(
    page_title="AML Workshop Simulator",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="auto",
)

STYLES = """
<style>
:root, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    --aml-line: var(--border-color);
    --aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
    --aml-danger: color-mix(in srgb, #ff2b2b 78%, var(--text-color));
    --aml-ok: color-mix(in srgb, #21c354 82%, var(--text-color));
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
    background: color-mix(in srgb, var(--aml-danger) 12%, var(--background-color));
    padding: .6rem .8rem; border-radius: 4px; margin: .35rem 0; font-size: 14px;
}
.aml-violation strong { color: var(--aml-danger); }
.aml-ok-box {
    border-left: 4px solid var(--aml-ok);
    background: color-mix(in srgb, var(--aml-ok) 12%, var(--background-color));
    padding: .6rem .8rem; border-radius: 4px; margin: .35rem 0; font-size: 14px;
}
.aml-step-meta { color: var(--aml-muted); font-size: 13px; }
.aml-delta { font-size: 13px; }
.aml-delta .down { color: var(--aml-danger); }
.aml-delta .up { color: var(--aml-ok); }
.aml-status-badge {
    display: inline-block; padding: .15rem .55rem; border-radius: 999px;
    border: 1px solid var(--aml-line); font-size: 12px; font-weight: 600;
}
table.aml-board, table.aml-table { width: 100%; border-collapse: collapse; font-size: 14px; }
table.aml-board th, table.aml-board td, table.aml-table th, table.aml-table td {
    border-bottom: 1px solid var(--aml-line); padding: .45rem .5rem; text-align: left;
}
.aml-scroll { overflow-x: auto; }
[data-testid="stMetricValue"] {
    font-size: clamp(1rem, 2.1vw, 1.6rem) !important;
    line-height: 1.25;
    white-space: normal;
    overflow-wrap: anywhere;
}
[data-testid="stMetricValue"] div { white-space: normal !important; }
[data-testid="stMetricLabel"] p { white-space: normal; }
@media (max-width: 1100px) {
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 320px;
        min-width: 260px;
    }
}
@media (max-width: 640px) {
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 1 1 100%;
        min-width: 100%;
    }
    .block-container { padding-left: .8rem; padding-right: .8rem; }
}
</style>
"""

STATUS_LABELS = {
    "draft": "Черновик",
    "submitted": "Отправлен",
    "scored": "Оценен",
    "none": "Не создан",
}
ROUND_STATUS_LABELS = {
    "draft": "Ожидает запуска",
    "active": "Идет",
    "stopped": "Остановлен",
    "scoring": "Подсчет результатов",
    "completed": "Завершен",
}
RISK_LABELS = {
    "normal": "Норма",
    "review": "Требует проверки",
    "suspicious": "Подозрительно",
}
PASSWORD_MIN_LENGTH = 10


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
        "preview_cache": {},
        "reveal_names": False,
        "selected_version": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def header(kicker: str, title: str, subtitle: str) -> None:
    """Render a page heading; appearance is controlled by Streamlit settings."""
    st.markdown(
        f'<div class="aml-kicker">{escape(kicker)}</div>', unsafe_allow_html=True
    )
    st.markdown(
        f'<div class="aml-title">{escape(title)}</div>', unsafe_allow_html=True
    )
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
    st.session_state["selected_version"] = scenario.get("revision")


def load_scenario(client: Any, round_id: int, session_id: str) -> None:
    scenario = client.get_scenario(round_id, session_id)
    if scenario:
        store_scenario(scenario)
    else:
        st.session_state["server_scenario"] = None
        st.session_state["server_revision"] = 0
        st.session_state["draft_steps"] = []
        st.session_state["selected_version"] = None
    st.session_state["chain_violations"] = []
    st.session_state["field_errors"] = {}
    st.session_state["loaded_for"] = (round_id, session_id)


# --------------------------------------------------------------------------
# Server preview: the single source of every number on screen
# --------------------------------------------------------------------------


def preview(
    client: Any, round_id: int, session_id: str, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    """Snapshot of `steps` computed by the server, memoised per payload.

    The chain does not have to be saved: this is what makes the balance, the
    energy, the quotas and the goal progress move the moment a step is added,
    edited, moved or removed.
    """
    key = json.dumps(
        [round_id, steps], sort_keys=True, ensure_ascii=False, default=str
    )
    cache: dict[str, Any] = st.session_state["preview_cache"]
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        result = client.preview_scenario(round_id, steps, session_id)
    except APIClientError as error:
        result = {
            "resources": {},
            "blockers": [],
            "error": error.message,
            "violations": (error.details or {}).get("violations", []),
        }
    # The snapshot of a given payload is deterministic for a given round, so it
    # is safe to remember; the cache is bounded because only the current chain
    # and the candidate step are ever read back.
    if len(cache) >= 32:
        cache.clear()
    cache[key] = result
    return result


def chain_snapshot(client: Any, round_id: int, session_id: str) -> dict[str, Any]:
    result = preview(client, round_id, session_id, st.session_state["draft_steps"])
    return result.get("resources") or {}


# --------------------------------------------------------------------------
# Server commands
# --------------------------------------------------------------------------


def save_draft(
    client: Any,
    round_id: int,
    session_id: str,
    *,
    quiet: bool = False,
    label: str | None = None,
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
            label=label or None,
        )
    except APIClientError as error:
        apply_error(error)
        return None
    finally:
        st.session_state["pending_command"] = None

    store_scenario(scenario)
    st.session_state["field_errors"] = {}
    if not quiet:
        resources = scenario.get("resources") or {}
        if resources.get("valid"):
            set_flash(
                "success",
                f"Черновик сохранен на сервере (версия {scenario['revision']}).",
            )
        else:
            set_flash(
                "warning",
                f"Черновик сохранен (версия {scenario['revision']}), "
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
    set_flash(
        "success",
        f"Версия {scenario['revision']} отправлена и ожидает скоринга организатора.",
    )


# --------------------------------------------------------------------------
# Login and registration
# --------------------------------------------------------------------------


def _registration_problems(
    display_name: str, email: str, password: str, confirmation: str
) -> list[str]:
    """Checks the browser can make before the request leaves the page."""
    problems: list[str] = []
    if not display_name.strip():
        problems.append("Укажите игровой псевдоним.")
    if not email.strip():
        problems.append("Укажите email.")
    elif "@" not in email or "." not in email.split("@")[-1]:
        problems.append("Email указан в неверном формате: ожидается вида name@example.com.")
    if not password:
        problems.append("Укажите пароль.")
    elif len(password) < PASSWORD_MIN_LENGTH:
        problems.append(
            f"Пароль должен содержать не менее {PASSWORD_MIN_LENGTH} символов."
        )
    if not confirmation:
        problems.append("Повторите пароль.")
    elif password and password != confirmation:
        problems.append("Пароли не совпадают.")
    return problems


def login_screen(client: Any) -> None:
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
            # A second click that was queued while the first request was in
            # flight must not create a second session.
            if st.session_state.get("session_id"):
                st.rerun()
                return
            if st.session_state.get("pending_command"):
                return
            problems = []
            if not email.strip():
                problems.append("Укажите email.")
            if not password:
                problems.append("Укажите пароль.")
            if problems:
                st.session_state["auth_error"] = " ".join(problems)
                st.rerun()
                return
            st.session_state["pending_command"] = "login"
            try:
                created = client.login(email.strip(), password, audience="play")
            except APIClientError as error:
                st.session_state["auth_error"] = error.message
                st.rerun()
                return
            finally:
                st.session_state["pending_command"] = None
            st.session_state["session_id"] = created["session_id"]
            st.session_state["user"] = created["user"]
            queue_cookie_set(created["session_id"], created.get("expires_at"))
            st.rerun()

    with tab_register:
        with st.form("register_form"):
            display_name = st.text_input("Игровой псевдоним", key="register_name")
            reg_email = st.text_input("Email", key="register_email")
            reg_password = st.text_input(
                f"Пароль (не менее {PASSWORD_MIN_LENGTH} символов)",
                type="password",
                key="register_password",
            )
            reg_password_repeat = st.text_input(
                "Повторите пароль", type="password", key="register_password_repeat"
            )
            registered = st.form_submit_button(
                "Зарегистрироваться", use_container_width=True
            )
        if registered:
            if st.session_state.get("pending_command"):
                return
            if st.session_state.get("registered_email") == reg_email.strip().lower():
                # The same queued click twice: the account already exists.
                st.rerun()
                return
            problems = _registration_problems(
                display_name, reg_email, reg_password, reg_password_repeat
            )
            if problems:
                st.session_state["auth_error"] = " ".join(problems)
                st.rerun()
                return
            st.session_state["pending_command"] = "register"
            try:
                client.register(reg_email.strip(), display_name.strip(), reg_password)
            except APIClientError as error:
                st.session_state["auth_error"] = error.message
                st.rerun()
                return
            finally:
                st.session_state["pending_command"] = None
            st.session_state["registered_email"] = reg_email.strip().lower()
            set_flash(
                "success", "Регистрация выполнена. Теперь войдите на вкладке «Вход»."
            )
            st.rerun()

    error_message = st.session_state.pop("auth_error", None)
    if error_message:
        st.error(error_message)
        marker("auth-error", error_message)


# --------------------------------------------------------------------------
# Scenario builder
# --------------------------------------------------------------------------


def default_step(card: dict[str, Any]) -> dict[str, Any]:
    """A new step carrying only the parameters this round exposes."""
    context: dict[str, Any] = {}
    details: dict[str, Any] = {}
    for param in card.get("visible_params", []):
        if param["namespace"] == "channel":
            context["channel"] = param["default"] or card["channels"][0]
        elif param["namespace"] == "context":
            context[param["key"]] = param["default"]
        else:
            details[param["key"]] = param["default"]
    context.setdefault("channel", card["channels"][0])
    return {
        "step_id": str(uuid.uuid4()),
        "card": {"id": card["id"], "code": card["code"], "version": card["version"]},
        "amount": f"{float(card['min_amount']):.2f}",
        "frequency": 1,
        "context": context,
        "action_details": details,
    }


def render_param(param: dict[str, Any], value: Any, widget_key: str) -> Any:
    """One control for one exposed parameter."""
    if param.get("kind") == "toggle":
        return st.toggle(
            param["label"],
            value=bool(value if value is not None else param.get("default")),
            key=widget_key,
            help=param.get("help"),
        )
    options = [option["value"] for option in param.get("options", [])]
    labels = {option["value"]: option["label"] for option in param.get("options", [])}
    if not options:
        return value
    current = value if value in options else param.get("default")
    index = options.index(current) if current in options else 0
    return st.selectbox(
        param["label"],
        options,
        index=index,
        format_func=lambda item: labels.get(item, item),
        key=widget_key,
        help=param.get("help"),
    )


def render_step_form(
    card: dict[str, Any], step: dict[str, Any], key_prefix: str
) -> dict[str, Any]:
    """Amount, optional frequency and the (at most two) exposed parameters."""
    context = dict(step.get("context") or {})
    details = dict(step.get("action_details") or {})
    show_frequency = bool(card.get("show_frequency", True))

    widths = [1.3, 0.7] if show_frequency else [1.0]
    columns = st.columns(widths + [1.2] * len(card.get("visible_params", [])))
    cursor = 0

    with columns[cursor]:
        amount = st.number_input(
            "Сумма, ₽ (от {} до {})".format(
                f"{float(card['min_amount']):,.0f}".replace(",", " "),
                f"{float(card['max_amount']):,.0f}".replace(",", " "),
            ),
            min_value=0.0,
            value=float(step["amount"]),
            step=1000.0,
            format="%.2f",
            key=f"{key_prefix}_amount",
        )
    cursor += 1

    frequency = int(step.get("frequency", 1))
    if show_frequency:
        with columns[cursor]:
            frequency = st.number_input(
                f"Повторов (до {card['max_frequency']})",
                min_value=1,
                max_value=int(card["max_frequency"]),
                value=min(int(step.get("frequency", 1)), int(card["max_frequency"])),
                step=1,
                key=f"{key_prefix}_frequency",
            )
        cursor += 1
    else:
        frequency = 1

    for param in card.get("visible_params", []):
        with columns[cursor]:
            if param["namespace"] == "channel":
                context["channel"] = render_param(
                    param, context.get("channel"), f"{key_prefix}_channel"
                )
            elif param["namespace"] == "context":
                context[param["key"]] = render_param(
                    param, context.get(param["key"]), f"{key_prefix}_ctx_{param['key']}"
                )
            else:
                details[param["key"]] = render_param(
                    param,
                    details.get(param["key"]),
                    f"{key_prefix}_detail_{param['key']}",
                )
        cursor += 1

    return {
        **step,
        "amount": f"{float(amount):.2f}",
        "frequency": int(frequency),
        "context": context,
        "action_details": details,
    }


def _resource_deltas(before: dict[str, Any], after: dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("balance", "баланс"),
        ("energy", "энергия"),
        ("time", "время"),
        ("trust", "доверие"),
    ):
        try:
            delta = float(after.get(key, 0)) - float(before.get(key, 0))
        except (TypeError, ValueError):
            continue
        if abs(delta) < 0.005:
            continue
        css = "down" if delta < 0 else "up"
        rendered = money(delta) if key == "balance" else f"{delta:+.0f}"
        if key == "balance" and delta > 0:
            rendered = f"+{rendered}"
        parts.append(f'<span class="{css}">{escape(label)} {escape(rendered)}</span>')
    return " · ".join(parts) or "без изменений"


def render_builder(
    client: Any,
    round_id: int,
    session_id: str,
    cards: dict[str, dict[str, Any]],
    max_actions: int,
) -> None:
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
    marker(
        "builder-params",
        ",".join(param["param"] for param in card.get("visible_params", [])),
    )

    draft_key = f"builder_step_{selected}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = default_step(card)
    step = render_step_form(card, st.session_state[draft_key], f"builder_{selected}")
    st.session_state[draft_key] = step

    steps: list[dict[str, Any]] = st.session_state["draft_steps"]
    candidate = {**step, "step_id": str(uuid.uuid4())}
    candidate_preview = preview(client, round_id, session_id, [*steps, candidate])
    candidate_resources = candidate_preview.get("resources") or {}
    candidate_blockers = [
        item
        for item in candidate_resources.get("violations", [])
        if item.get("step_index") in (None, len(steps) + 1)
    ]
    structural = candidate_preview.get("violations") or []

    if candidate_resources.get("per_step"):
        impact = candidate_resources["per_step"][-1]
        st.markdown(
            '<div class="aml-delta" data-testid="candidate-impact">Влияние шага: '
            f"{_resource_deltas(impact.get('resources_before', {}), impact.get('resources_after', {}))}"
            "</div>",
            unsafe_allow_html=True,
        )

    limit_reached = len(steps) >= max_actions
    blocked = bool(structural) or limit_reached
    if st.button(
        "Добавить в цепочку",
        type="primary",
        use_container_width=True,
        key="add_step",
        disabled=blocked,
    ):
        steps.append(candidate)
        st.session_state[draft_key] = default_step(card)
        st.rerun()

    if limit_reached:
        st.warning(
            f"Достигнут лимит раунда: {max_actions} операций. "
            "Удалите шаг, чтобы добавить новый."
        )
        marker("add-blocked-reason", "max_actions")
    for violation in structural:
        st.markdown(
            f'<div class="aml-violation" data-testid="candidate-structural">'
            f"{escape(violation.get('message', ''))}</div>",
            unsafe_allow_html=True,
        )
    for violation in candidate_blockers:
        st.markdown(
            f'<div class="aml-violation" data-testid="candidate-violation-'
            f'{escape(violation.get("reason", ""))}">'
            f"{escape(violation.get('message', ''))}</div>",
            unsafe_allow_html=True,
        )
    if not blocked and not candidate_blockers:
        marker("add-blocked-reason", "")


def render_chain(
    client: Any,
    round_id: int,
    session_id: str,
    cards_by_key: dict[tuple[str, int], dict[str, Any]],
    editable: bool,
) -> None:
    steps: list[dict[str, Any]] = st.session_state["draft_steps"]
    st.subheader(f"Цепочка операций ({len(steps)})")
    marker("chain-length", len(steps))
    if not steps:
        st.info("Цепочка пуста. Настройте операцию слева и добавьте её в цепочку.")
        return

    snapshot = chain_snapshot(client, round_id, session_id)
    per_step = {item["step_id"]: item for item in snapshot.get("per_step", [])}
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
                step["context"].get("channel"), step["context"].get("channel", "")
            )
            frequency_text = (
                f" × {step['frequency']}" if int(step.get("frequency", 1)) > 1 else ""
            )
            st.markdown(
                f'<div class="aml-step-meta">{money(step["amount"])}{frequency_text}'
                f' · канал: <span data-testid="step-channel-{escape(step_id)}">'
                f"{escape(str(channel_label))}</span></div>",
                unsafe_allow_html=True,
            )
            if impact:
                before = impact.get("resources_before", {})
                after = impact.get("resources_after", {})
                st.markdown(
                    f'<div class="aml-delta" data-testid="step-impact-{escape(step_id)}">'
                    f"До: {escape(money(before.get('balance')))} · "
                    f"энергия {escape(str(before.get('energy')))} · "
                    f"время {escape(str(before.get('time')))} · "
                    f"доверие {escape(str(before.get('trust')))}<br>"
                    f"После: {escape(money(after.get('balance')))} · "
                    f"энергия {escape(str(after.get('energy')))} · "
                    f"время {escape(str(after.get('time')))} · "
                    f"доверие {escape(str(after.get('trust')))}"
                    "</div>",
                    unsafe_allow_html=True,
                )
                marker(f"step-balance-after-{step_id}", after.get("balance", ""))
            for field, message in step_errors.items():
                st.markdown(
                    f'<div class="aml-violation" data-testid="step-error-{escape(step_id)}-'
                    f'{escape(field)}"><strong>{escape(field)}</strong>: {escape(message)}</div>',
                    unsafe_allow_html=True,
                )

            if editable and card is not None:
                with st.expander(
                    "Изменить шаг",
                    expanded=st.session_state["editing_step_id"] == step_id,
                ):
                    updated = render_step_form(card, step, f"edit_{step_id}")
                    if updated != step:
                        steps[index] = updated
                        st.rerun()
                col_up, col_down, col_copy, col_delete = st.columns(4)
                with col_up:
                    if st.button(
                        "Вверх",
                        key=f"up_{step_id}",
                        disabled=index == 0,
                        use_container_width=True,
                    ):
                        move = (index, index - 1)
                with col_down:
                    if st.button(
                        "Вниз",
                        key=f"down_{step_id}",
                        disabled=index == len(steps) - 1,
                        use_container_width=True,
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


def render_resources(snapshot: dict[str, Any], game_config: dict[str, Any]) -> None:
    """Live resources: whatever the server says about the current chain."""
    config_resources = game_config.get("resources", {})
    config_objectives = game_config.get("objectives", {})
    after = snapshot.get("resources_after") or {
        "balance": config_resources.get("initial_balance", "0"),
        "energy": config_resources.get("initial_energy", 0),
        "time": config_resources.get("initial_time", 0),
        "trust": config_resources.get("initial_trust", 0),
        "slots": config_objectives.get("max_actions", 0),
    }
    totals = snapshot.get("totals") or {"gross_outflow": "0", "fees": "0"}
    objective = snapshot.get("objective") or {
        "target_outflow": config_objectives.get("target_outflow", "0"),
        "reached": False,
    }

    columns = st.columns(5)
    values = (
        ("Баланс", money(after.get("balance", 0)), "balance"),
        ("Энергия", after.get("energy", 0), "energy"),
        ("Время", after.get("time", 0), "time"),
        ("Доверие", after.get("trust", 0), "trust"),
        ("Свободных слотов", after.get("slots", 0), "slots"),
    )
    for column, (label, value, testid) in zip(columns, values, strict=False):
        with column:
            st.metric(label, value)
            marker(f"resource-{testid}", value)

    reached = bool(objective.get("reached"))
    marker("objective-reached", "true" if reached else "false")
    marker("resources-valid", "true" if snapshot.get("valid") else "false")

    target = float(objective.get("target_outflow", 0) or 0)
    current = float(totals.get("gross_outflow", 0) or 0)
    st.progress(min(1.0, current / target) if target else 0.0)
    st.caption(
        f"Цель раунда: расходный оборот {money(current)} из {money(target)} · "
        f"комиссии {money(totals.get('fees', 0))}"
    )
    marker("objective-progress", f"{current:.2f}/{target:.2f}")


def render_limits(snapshot: dict[str, Any]) -> None:
    limits = snapshot.get("limits") or []
    if not limits:
        return
    with st.expander("Квоты и лимиты раунда", expanded=False):
        rows = "".join(
            "<tr>"
            f"<td>{escape(str(item['label']))}</td>"
            f"<td>{escape(money(item['used']) if item.get('kind') == 'money' else str(item['used']))}</td>"
            f"<td>{escape(money(item['limit']) if item.get('kind') == 'money' else str(item['limit']))}</td>"
            f"<td>{escape(money(item['remaining']) if item.get('kind') == 'money' else str(item['remaining']))}</td>"
            "</tr>"
            for item in limits
        )
        st.markdown(
            '<div class="aml-scroll"><table class="aml-table" data-testid="limits-table">'
            "<thead><tr><th>Лимит</th><th>Использовано</th><th>Ограничение</th>"
            f"<th>Осталось</th></tr></thead><tbody>{rows}</tbody></table></div>",
            unsafe_allow_html=True,
        )
    marker("limits-count", len(limits))


def render_violations(snapshot: dict[str, Any]) -> None:
    violations = snapshot.get("violations") or []
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


def render_versions(client: Any, round_id: int, session_id: str) -> None:
    """The participant's own saved history, stored in PostgreSQL."""
    scenario = st.session_state.get("server_scenario")
    if not scenario:
        marker("version-count", 0)
        st.caption("История появится после первого сохранения черновика.")
        return
    try:
        page = client.list_scenario_versions(round_id, session_id)
    except APIClientError as error:
        st.error(error.message)
        return
    rows = page.get("rows", [])
    marker("version-count", len(rows))
    if not rows:
        st.caption("История появится после первого сохранения черновика.")
        return

    body = "".join(
        "<tr>"
        f"<td>{row['revision']}</td>"
        f"<td>{escape(row.get('label') or '—')}</td>"
        f"<td>{row['step_count']}</td>"
        f"<td>{escape(str(row['created_at'])[:19].replace('T', ' '))}</td>"
        f"<td>{'да' if row['valid'] else 'нет'}</td>"
        f"<td>{'текущая' if row['is_current'] else ('отправлена' if row['is_submitted'] else '')}</td>"
        "</tr>"
        for row in rows
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-table" data-testid="versions-table">'
        "<thead><tr><th>Версия</th><th>Название</th><th>Шагов</th><th>Сохранена</th>"
        f"<th>Без нарушений</th><th>Статус</th></tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    options = {
        f"Версия {row['revision']}"
        + (f" · {row['label']}" if row.get("label") else "")
        + (" · текущая" if row["is_current"] else ""): row
        for row in rows
    }
    chosen = st.selectbox("Открыть версию", list(options), key="version_select")
    row = options[chosen]
    marker("selected-version", row["revision"])
    if row["is_current"]:
        st.caption("Это текущая версия черновика.")
        return
    if st.button(
        "Продолжить с этой версии",
        key="restore_version",
        use_container_width=True,
        disabled=bool(st.session_state.get("pending_command")),
    ):
        st.session_state["pending_command"] = "restore"
        try:
            scenario = client.restore_scenario_version(
                round_id,
                row["revision"],
                st.session_state["server_revision"],
                session_id,
                client_mutation_id=str(uuid.uuid4()),
            )
        except APIClientError as error:
            apply_error(error)
            st.rerun()
            return
        finally:
            st.session_state["pending_command"] = None
        store_scenario(scenario)
        set_flash(
            "success",
            f"Восстановлена версия {row['revision']}: она сохранена как новая "
            f"версия {scenario['revision']}, прежние версии остались в истории.",
        )
        st.rerun()


def waiting_screen(round_obj: dict[str, Any] | None) -> None:
    status = (round_obj or {}).get("status", "none")
    header(
        "Раунд",
        "Ожидание раунда",
        "Организатор ещё не запустил раунд. Как только он нажмёт «Начать раунд», "
        "конструктор откроется автоматически — страницу можно просто обновить.",
    )
    marker("round-status", status)
    marker("scenario-status", "none")
    if round_obj:
        st.info(
            f"Раунд «{round_obj['title']}» находится в статусе "
            f"«{ROUND_STATUS_LABELS.get(status, status)}»."
        )
    else:
        st.info("Раунд ещё не создан организатором.")


def page_scenario() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    try:
        current_round = client.get_current_round()
    except APIClientError as error:
        st.error(error.message)
        marker("api-error", error.code)
        return

    if not current_round or current_round["status"] == "draft":
        waiting_screen(current_round)
        return

    round_id = current_round["id"]
    editable_round = current_round["status"] == "active"
    if st.session_state.get("loaded_for") != (round_id, session_id):
        load_scenario(client, round_id, session_id)

    game_config = current_round.get("game_config") or {}
    max_actions = int((game_config.get("objectives") or {}).get("max_actions", 0) or 0)

    cards_list = client.get_round_cards(round_id)
    cards = {card["code"]: card for card in cards_list}
    cards_by_key = {(card["code"], card["version"]): card for card in cards_list}

    scenario = st.session_state.get("server_scenario")
    status = (scenario or {}).get("status", "none")
    editable = status in {"draft", "none"} and editable_round

    header(
        f"Раунд #{round_id}",
        "Конструктор сценария",
        "Соберите цепочку операций, сохраните черновик и отправьте её на скоринг.",
    )
    marker("scenario-status", status)
    marker("scenario-revision", (scenario or {}).get("revision", 0))
    marker("round-status", current_round["status"])
    marker("max-actions", max_actions)
    st.markdown(
        f'<span class="aml-status-badge" data-testid="status-badge">'
        f"Статус: {escape(STATUS_LABELS.get(status, status))}"
        f"{' · версия ' + str(scenario['revision']) if scenario else ''}</span>",
        unsafe_allow_html=True,
    )
    show_flash()

    snapshot = chain_snapshot(client, round_id, session_id)
    render_resources(snapshot, game_config)
    render_limits(snapshot)
    render_violations(snapshot)
    st.divider()

    if not editable:
        st.info(
            "Сценарий зафиксирован сервером. Изменение доступно, только пока раунд "
            "идет и сценарий находится в черновике."
        )
        render_chain(client, round_id, session_id, cards_by_key, editable=False)
        with st.expander("История сохранённых черновиков", expanded=False):
            render_versions(client, round_id, session_id)
        return

    builder_column, chain_column = st.columns([1.0, 1.1], gap="large")
    with builder_column:
        render_builder(client, round_id, session_id, cards, max_actions)
    with chain_column:
        render_chain(client, round_id, session_id, cards_by_key, editable=True)

        st.divider()
        synchronized = st.session_state["draft_steps"] == (scenario or {}).get("steps", [])
        can_submit = (
            bool(scenario)
            and synchronized
            and bool(snapshot.get("valid"))
            and bool((snapshot.get("objective") or {}).get("reached"))
        )
        marker("submit-enabled", "true" if can_submit else "false")
        marker("draft-synchronized", "true" if synchronized else "false")

        label = st.text_input(
            "Название версии (необязательно)", key="draft_label", max_chars=120
        )
        save_column, submit_column = st.columns(2)
        with save_column:
            if st.button(
                "Сохранить черновик",
                key="save_draft",
                use_container_width=True,
                disabled=bool(st.session_state.get("pending_command")),
            ):
                save_draft(client, round_id, session_id, label=label)
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

    st.divider()
    st.subheader("История сохранённых черновиков")
    render_versions(client, round_id, session_id)


def page_result() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header(
        "Результат",
        "Оценка учебной модели",
        "Разбор факторов и ресурсов.",
    )

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
    header(
        "Лидерборд",
        "Итоги раунда",
        "Ники скрыты по умолчанию: сервер отдаёт обезличенные места, пока их не "
        "раскроют явно.",
    )

    rounds = client.get_my_rounds(session_id).get("rows", [])
    if not rounds:
        st.info("Раундов пока нет.")
        return
    options = {f"#{row['id']} · {row['title']}": row for row in rounds}
    chosen = st.selectbox("Раунд", list(options), key="board_round")

    reveal = bool(st.session_state.get("reveal_names"))
    marker("names-revealed", "true" if reveal else "false")
    control_column, _ = st.columns([1, 3])
    with control_column:
        if reveal:
            if st.button("Скрыть ники", key="hide_names", use_container_width=True):
                st.session_state["reveal_names"] = False
                st.rerun()
        else:
            if st.button(
                "Показать все ники", key="reveal_names", use_container_width=True
            ):
                st.session_state["reveal_names"] = True
                st.rerun()

    board = client.get_leaderboard(options[chosen]["id"], session_id, reveal=reveal)
    rows = board.get("rows", [])
    marker("leaderboard-rows", len(rows))
    if not rows:
        st.info("Лидерборд появится после завершения раунда.")
        return
    body = "".join(
        "<tr>"
        f"<td>{row['rank']}</td>"
        f"<td>{escape(row['display_name'])}{' · вы' if row.get('is_current_user') else ''}</td>"
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
    apply_pending_cookie_command(controller, PLAY_COOKIE)
    st.markdown(STYLES, unsafe_allow_html=True)

    session = resolve_session(controller, PLAY_COOKIE, client)
    if consume_hydration_flag():
        # Restart the run so the login tree is replaced, not overlaid.
        st.rerun()

    if session.pending:
        st.info("Восстанавливаем сессию…")
        marker("auth-state", "pending")
        st.stop()

    if not session.authenticated:
        login_screen(client)
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
            queue_cookie_clear()
            reset_user_state()
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
