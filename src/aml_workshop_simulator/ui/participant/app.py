from __future__ import annotations

import sys
from html import escape
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import pandas as pd
import streamlit as st

from src.aml_workshop_simulator.ui.shared.api_client import (
    SimulatorAPIClient,
    APIClientError,
)
from src.aml_workshop_simulator.ui.shared.components import (
    render_catboost_features_inspector,
)
from src.aml_workshop_simulator.services.local_rules import (
    INITIAL_BALANCE,
    INITIAL_ENERGY,
    INITIAL_TIME,
    INITIAL_TRUST,
    MAX_ACTIONS,
    MAX_IDENTICAL_STEPS,
    MAX_NIGHT_OPERATIONS,
    TARGET_OUTFLOW,
    CHANNEL_LABELS,
    COUNTRY_RISK_LABELS,
    RECIPIENT_TYPE_LABELS,
    TIME_OF_DAY_LABELS,
    VELOCITY_LABELS,
)
from src.aml_workshop_simulator.services.action_parameters import (
    action_fields_for,
    context_fields_for,
    context_value_label,
    default_action_details,
    default_context,
    detail_factor_label,
    normalize_action_details,
    action_detail_summary,
)
from src.aml_workshop_simulator.services.scenario_service import (
    calculate_resource_snapshot,
)

st.set_page_config(
    page_title="AML: игра против алгоритма",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --aml-ink: var(--text-color);
        --aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
        --aml-line: color-mix(in srgb, var(--text-color) 18%, transparent);
        --aml-surface: var(--secondary-background-color);
        --aml-soft: color-mix(in srgb, var(--primary-color) 9%, var(--background-color));
        --aml-primary: var(--primary-color);
        --aml-warning: #d89022;
        --aml-danger: #d65353;
        --aml-success: #2e9e5b;
    }
    .block-container {
        max-width: 1180px;
        padding-top: 1.5rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid var(--aml-line);
    }
    [data-testid="stMetric"] {
        min-height: 88px;
        padding: .8rem .9rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    .aml-kicker {
        margin-bottom: .35rem;
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        color: var(--aml-primary);
    }
    .aml-page-title {
        margin: 0 0 .35rem;
        font-size: 32px !important;
        font-weight: 800;
        line-height: 1.15 !important;
    }
    .aml-subtitle {
        max-width: 780px;
        margin: 0 0 1.25rem;
        color: var(--aml-muted);
        font-size: 15px;
    }
    .aml-brand {
        padding: .35rem 0 .8rem;
        border-bottom: 1px solid var(--aml-line);
    }
    .aml-brand-title {font-size: 17px; font-weight: 700;}
    .aml-brand-caption {margin-top: .2rem; font-size: 12px; color: var(--aml-muted);}
    .aml-player {
        padding: .75rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
        margin: .5rem 0;
    }
    .aml-player-name {font-weight: 700;}
    .aml-player-email {color: var(--aml-muted); font-size: 12px;}
    .aml-card-specs {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .5rem;
        margin: .75rem 0;
    }
    .aml-spec {
        padding: .5rem .6rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
        font-size: 12px;
    }
    .aml-spec span {display: block; color: var(--aml-muted); font-size: 11px;}
    .aml-spec strong {display: block; margin-top: .15rem;}
    .aml-impact-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .5rem;
        margin: .5rem 0 .8rem;
    }
    .aml-impact {
        padding: .5rem .6rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
        font-size: 12px;
    }
    .aml-impact span {display: block; color: var(--aml-muted); font-size: 11px;}
    .aml-impact strong {display: block; margin-top: .15rem; color: var(--aml-primary);}
    .aml-score-hero {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .75rem;
        margin: 1rem 0;
    }
    .aml-score-main {
        padding: 1rem;
        border: 2px solid var(--aml-primary);
        border-radius: 8px;
        background: var(--aml-soft);
    }
    .aml-score-detail {
        padding: 1rem;
        border: 1px solid var(--aml-line);
        border-radius: 8px;
        background: var(--aml-surface);
    }
    .aml-score-label {color: var(--aml-muted); font-size: 13px;}
    .aml-score-value {font-size: 22px; font-weight: 700; margin-top: .25rem;}
    .aml-status-box {
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid var(--aml-primary);
        background: var(--aml-surface);
        margin: 1rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_api_client() -> SimulatorAPIClient:
    return SimulatorAPIClient()


def init_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "user" not in st.session_state:
        st.session_state.user = None
    if "draft_steps" not in st.session_state:
        st.session_state.draft_steps = []
    if "expected_revision" not in st.session_state:
        st.session_state.expected_revision = 0
    if "server_scenario" not in st.session_state:
        st.session_state.server_scenario = None
    if "loaded_user_id" not in st.session_state:
        st.session_state.loaded_user_id = None


def format_money(val: float | int) -> str:
    return f"{val:,.0f} ₽".replace(",", " ")


def signed_money(val: float | int) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}{val:,.0f} ₽".replace(",", " ")


def render_page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(f'<div class="aml-kicker">{escape(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="aml-page-title">{escape(title)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="aml-subtitle">{escape(subtitle)}</div>', unsafe_allow_html=True)


def sync_scenario_from_server(client: SimulatorAPIClient, round_id: int, session_id: str, user_id: int) -> dict[str, Any] | None:
    """Fetch scenario from server and sync session_state if not already synced for this user."""
    try:
        scen = client.get_scenario(round_id, session_id)
        st.session_state.server_scenario = scen
        if scen:
            st.session_state.draft_steps = scen.get("steps", [])
            st.session_state.expected_revision = scen.get("revision", 0)
        st.session_state.loaded_user_id = user_id
        return scen
    except Exception as e:
        return None


def login_screen(client: SimulatorAPIClient) -> None:
    render_page_header(
        "AML Workshop Simulator",
        "Вход в симулятор",
        "Авторизуйтесь или создайте игровой профиль для участия в раунде.",
    )

    tab_login, tab_register = st.tabs(["Вход в систему", "Регистрация"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", value="demo@aml.local")
            password = st.text_input("Пароль", type="password", value="demo12345")
            submit = st.form_submit_button("Войти в игру", use_container_width=True, type="primary")

            if submit:
                try:
                    res = client.login(email.strip(), password, audience="play")
                    st.session_state.session_id = res["session_id"]
                    st.session_state.user = res["user"]
                    st.session_state.loaded_user_id = None
                    st.success("Успешный вход!")
                    st.rerun()
                except APIClientError as e:
                    st.error(f"Ошибка входа: {e.message}")

    with tab_register:
        with st.form("register_form"):
            reg_name = st.text_input("Игровой псевдоним", value="Финансовый стратег")
            reg_email = st.text_input("Email")
            reg_pass = st.text_input("Пароль", type="password")
            reg_submit = st.form_submit_button("Зарегистрироваться", use_container_width=True)

            if reg_submit:
                try:
                    client.register(reg_email.strip(), reg_name.strip(), reg_pass)
                    st.success("Регистрация успешна! Теперь выполните вход на вкладке 'Вход'.")
                except APIClientError as e:
                    st.error(f"Ошибка регистрации: {e.message}")


def render_resource_dashboard(resources: dict[str, Any]) -> None:
    res = resources.get("resources_after", {}) if "resources_after" in resources else resources
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Баланс", format_money(float(res.get("balance", 0))))
    with c2:
        st.metric("Энергия", f"{int(res.get('energy', 0))} ед.")
    with c3:
        st.metric("Время", f"{int(res.get('time', 0))} ч.")
    with c4:
        st.metric("Доверие", f"{int(res.get('trust', 0))} %")
    with c5:
        st.metric("Слотов свободно", f"{int(res.get('slots', 0))}")


def render_round_limits(resources: dict[str, Any]) -> None:
    limits = resources.get("limits", [])
    if limits:
        rows = []
        for item in limits:
            rows.append(
                {
                    "Квота": item["label"],
                    "Использовано": format_money(item["used"]),
                    "Лимит": format_money(item["limit"]),
                    "Осталось": format_money(item["remaining"]),
                    "Статус": "⚠️ Превышен" if item["used"] > item["limit"] else "✅ В норме",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption(
        f"Дополнительно: не более {MAX_NIGHT_OPERATIONS} ночных операций и "
        f"не более {MAX_IDENTICAL_STEPS} одинаковых шагов подряд."
    )


def render_home() -> None:
    client = get_api_client()
    session_id = st.session_state.session_id
    user = st.session_state.user

    try:
        active_round = client.get_active_round()
    except Exception as e:
        st.error(f"Ошибка загрузки раунда: {e}")
        return

    if not active_round:
        render_page_header("AML Simulator", f"Добро пожаловать, {user.get('display_name')}", "Ожидание раунда")
        st.warning("В данный момент нет активного раунда. Ожидайте запуска организатором.")
        if st.button("🔄 Проверить статус"):
            st.rerun()
        return

    round_id = active_round["id"]
    scenario_info = st.session_state.server_scenario

    render_page_header(
        f"Раунд #{round_id} · {active_round['title']}",
        f"Добро пожаловать, {user.get('display_name')}",
        "Проведите нужный оборот, сохраните ресурсы и соберите оптимальный маршрут.",
    )

    task_col, rating_col = st.columns([1.35, 1], gap="large")
    with task_col:
        st.subheader("🎯 Игровая задача")
        st.write(
            f"Проведите не менее **{format_money(TARGET_OUTFLOW)}** через расходные операции "
            f"максимум за **{MAX_ACTIONS}** действий. Баланс, энергия, время и доверие не должны опуститься ниже нуля."
        )
        c_goal, c_bal, c_stat = st.columns(3)
        with c_goal:
            st.metric("Цель оборота", format_money(TARGET_OUTFLOW))
        with c_bal:
            st.metric("Стартовый баланс", format_money(INITIAL_BALANCE))
        with c_stat:
            status_text = "Черновик"
            if scenario_info:
                if scenario_info.get("status") == "submitted":
                    status_text = "🟢 Отправлен"
                elif scenario_info.get("status") == "scored":
                    status_text = "🏁 Оценен"
                else:
                    status_text = "✏️ Черновик"
            st.metric("Статус сценария", status_text)

    with rating_col:
        st.subheader("📊 Формула рейтинга")
        st.write(
            "60% итогового балла дает незаметность для AML-модели (100 − Риск). "
            "Остальные 40% зависят от сохраненных ресурсов, комиссий и числа действий."
        )
        st.progress(0.6, text="Незаметность (ML Модель) · 60%")
        st.progress(0.4, text="Эффективность ресурсов · 40%")

    st.divider()
    c_btn1, c_btn2 = st.columns([2, 1])
    with c_btn1:
        if st.button("🛠️ Перейти в Конструктор сценария", type="primary", use_container_width=True):
            st.switch_page(scenario_page)
    with c_btn2:
        if st.button("🏆 Открыть Лидерборд", use_container_width=True):
            st.switch_page(leaderboard_page)


def render_scenario() -> None:
    client = get_api_client()
    session_id = st.session_state.session_id
    steps = st.session_state.draft_steps
    server_scen = st.session_state.server_scenario

    try:
        active_round = client.get_active_round()
    except Exception as e:
        st.error(f"Ошибка загрузки раунда: {e}")
        return

    if not active_round:
        st.warning("Нет активного раунда.")
        return

    round_id = active_round["id"]
    try:
        cards_catalog = client.get_round_cards(round_id)
    except Exception as e:
        st.error(f"Ошибка загрузки карточек: {e}")
        return

    is_submitted = server_scen and server_scen.get("status") == "submitted"

    render_page_header(
        "Конструктор сценария",
        "Соберите финансовый маршрут" if not is_submitted else "Зафиксированный сценарий",
        "Добавляйте операции и проверяйте порядок шагов, ресурсы и ограничения раунда." if not is_submitted else "Ваш сценарий успешно отправлен в БД и ожидает запуска общего скоринга.",
    )

    resources = calculate_resource_snapshot(steps, active_round.get("game_config"))
    render_resource_dashboard(resources)

    with st.expander("Квоты и жесткие ограничения"):
        render_round_limits(resources)

    st.markdown("---")

    if is_submitted:
        st.success(
            f"✅ **Сценарий зафиксирован в базе данных (Ревизия #{server_scen.get('revision')}).** "
            "Изменение заблокировано. Ожидайте запуска общего скоринга организатором мероприятия."
        )

        col_left, col_right = st.columns([1.2, 0.8], gap="large")
        with col_left:
            render_scenario_steps_readonly(steps, cards_catalog, resources)
        with col_right:
            st.subheader("🎯 Результаты валидации")
            st.write(f"Оборот: **{format_money(float(resources['totals']['gross_outflow']))}** из {format_money(TARGET_OUTFLOW)}")
            st.write(f"Уплачено комиссий: **{format_money(float(resources['totals']['fees']))}**")
            st.write(f"Действий в цепочке: **{len(steps)}** из {MAX_ACTIONS}")
            if st.button("🔄 Проверить готовность результатов", type="primary", use_container_width=True):
                st.switch_page(result_page)
        return

    # Normal Editable Builder
    builder_col, sequence_col = st.columns([1.05, 0.95], gap="large")
    with builder_col:
        render_action_builder(steps, cards_catalog)
    with sequence_col:
        render_scenario_steps(steps, cards_catalog, resources, round_id, client, session_id)


def render_action_builder(steps: list[dict[str, Any]], cards_catalog: list[dict[str, Any]]) -> None:
    st.subheader("➕ Настройка новой операции")
    card_options = {f"{c['title']} · {c['category']}": c for c in cards_catalog}
    selected_label = st.selectbox("Тип операции", list(card_options.keys()))
    card = card_options[selected_label]
    code = card["code"]

    desc = card.get("description", "")
    if desc:
        st.caption(f"💡 {desc}")

    specs = (
        ("Сумма", f"{format_money(float(card['min_amount']))} - {format_money(float(card['max_amount']))}"),
        ("Повторы", f"до {card['max_frequency']} за шаг"),
        ("Ресурсы", f"{card['costs'].get('energy', 1)} эн. · {card['costs'].get('time', 1)} вр."),
        ("Комиссия", f"{float(card['fee_rate']) * 100:g}%"),
    )
    spec_html = "".join(
        f'<div class="aml-spec"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in specs
    )
    st.markdown(f'<div class="aml-card-specs">{spec_html}</div>', unsafe_allow_html=True)

    basic_tab, context_tab = st.tabs(["Операция", "Контекст"])

    with basic_tab:
        amount_col, freq_col = st.columns([1.55, 0.85])
        with amount_col:
            amount = st.number_input(
                "Сумма платежа, ₽",
                min_value=float(card["min_amount"]),
                max_value=float(card["max_amount"]),
                value=min(50_000.0, float(card["max_amount"])),
                step=5000.0,
                key=f"new_amount_{code}",
            )
        with freq_col:
            frequency = st.number_input(
                "Повторов",
                min_value=1,
                max_value=int(card["max_frequency"]),
                value=1,
                key=f"new_freq_{code}",
            )

        channel_options = card.get("channels", ["bank", "mobile", "web"])
        channel = st.selectbox(
            "Канал",
            channel_options,
            format_func=lambda v: CHANNEL_LABELS.get(v, v),
            key=f"new_chan_{code}",
        )

        action_fields = card.get("fields", [])
        detail_values: dict[str, Any] = {}
        if action_fields:
            st.markdown("##### Детали платежа")
            for af in action_fields:
                k = af["key"]
                opts = {o["label"]: o["value"] for o in af.get("options", [])}
                if opts:
                    chosen = st.selectbox(af["label"], list(opts.keys()), key=f"new_detail_{k}_{code}")
                    detail_values[k] = opts[chosen]

    with context_tab:
        ctx_fields = card.get("context_fields", [])
        context_values: dict[str, Any] = {}
        for cf in ctx_fields:
            k = cf["key"]
            if cf.get("kind") == "toggle":
                context_values[k] = st.toggle(cf["label"], value=cf.get("default", True), key=f"new_ctx_{k}_{code}")
            elif cf.get("options"):
                opts = {o["label"]: o["value"] for o in cf["options"]}
                chosen = st.selectbox(cf["label"], list(opts.keys()), key=f"new_ctx_{k}_{code}")
                context_values[k] = opts[chosen]

    proposed_step = {
        "uid": str(uuid4()),
        "card_code": code,
        "card": {"id": card["id"], "code": code, "version": card["version"]},
        "amount": amount,
        "frequency": frequency,
        "channel": channel,
        "context": {**context_values, "channel": channel},
        "action_details": detail_values,
        "details": detail_values,
    }

    proposed_res = calculate_resource_snapshot([*steps, proposed_step])
    proposed_impacts = proposed_res.get("steps") or proposed_res.get("per_step") or []
    proposed_impact = proposed_impacts[-1] if proposed_impacts else {
        "money_delta": 0, "energy_cost": 0, "time_cost": 0, "trust_cost": 0
    }
    impacts = (
        ("Баланс", signed_money(proposed_impact.get("money_delta", 0))),
        ("Энергия", f"−{proposed_impact.get('energy_cost', 0)}"),
        ("Время", f"−{proposed_impact.get('time_cost', 0)}"),
        ("Доверие", f"−{proposed_impact.get('trust_cost', 0)}"),
    )
    impact_html = "".join(
        f'<div class="aml-impact"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in impacts
    )
    st.markdown(
        '<div style="font-size:12px; font-weight:700; margin-top:.5rem;">Влияние нового шага:</div>'
        f'<div class="aml-impact-grid">{impact_html}</div>',
        unsafe_allow_html=True,
    )

    cannot_add = len(steps) >= MAX_ACTIONS or not proposed_res["valid"]
    if st.button("➕ Добавить в цепочку", type="primary", use_container_width=True, disabled=cannot_add):
        steps.append(proposed_step)
        st.session_state.draft_steps = steps
        st.rerun()

    if cannot_add:
        reason = (
            f"Достигнут лимит: {MAX_ACTIONS} действий."
            if len(steps) >= MAX_ACTIONS
            else proposed_res["violations"][0]
        )
        st.warning(reason)


def render_scenario_steps_readonly(
    steps: list[dict[str, Any]],
    cards_catalog: list[dict[str, Any]],
    resources: dict[str, Any],
) -> None:
    st.subheader(f"📋 Зафиксированная цепочка ({len(steps)} из {MAX_ACTIONS} действий)")
    card_lookup = {c["code"]: c for c in cards_catalog}
    step_impacts = resources.get("steps") or resources.get("per_step") or []

    for idx, step in enumerate(steps):
        code = step["card_code"]
        card = card_lookup.get(code, {"title": code, "icon": "💳"})
        impact = step_impacts[idx] if idx < len(step_impacts) else {}

        with st.container(border=True):
            st.markdown(f"**{idx + 1}. {card['title']}** — `{format_money(step['amount'])}` × `{step['frequency']}`")
            st.caption(
                f"баланс {signed_money(impact.get('money_delta', 0))} · "
                f"энергия −{impact.get('energy_cost', 0)} · время −{impact.get('time_cost', 0)} · "
                f"доверие −{impact.get('trust_cost', 0)}"
            )
            ctx = step.get("context", {})
            summary_parts = []
            if ctx.get("country_risk") == "high":
                summary_parts.append("⚠️ Высокий риск страны")
            if ctx.get("recipient_type") == "anonymous_wallet":
                summary_parts.append("🕵️ Анонимный кошелек")
            if ctx.get("time_of_day") == "night":
                summary_parts.append("🌙 Ночь")
            if ctx.get("velocity") == "rapid":
                summary_parts.append("⚡ Быстрый темп")
            if not ctx.get("has_documents", True):
                summary_parts.append("❌ Без документов")
            if summary_parts:
                st.caption(" | ".join(summary_parts))


def render_scenario_steps(
    steps: list[dict[str, Any]],
    cards_catalog: list[dict[str, Any]],
    resources: dict[str, Any],
    round_id: int,
    client: SimulatorAPIClient,
    session_id: str,
) -> None:
    c_title, c_cnt = st.columns([3, 1])
    with c_title:
        st.subheader("📋 Цепочка операций")
    with c_cnt:
        st.caption(f"{len(steps)} из {MAX_ACTIONS} действий")

    if not steps:
        st.info("Цепочка пока пуста. Настройте и добавьте первую операцию слева.")
        return

    card_lookup = {c["code"]: c for c in cards_catalog}
    move_action = None
    delete_idx = None
    step_impacts = resources.get("steps") or resources.get("per_step") or []

    for idx, step in enumerate(steps):
        code = step["card_code"]
        card = card_lookup.get(code, {"title": code, "icon": "💳"})
        impact = step_impacts[idx] if idx < len(step_impacts) else {}

        with st.container(border=True):
            st.markdown(f"**{idx + 1}. {card['title']}**")
            st.caption(
                f"{format_money(step['amount'])} × {step['frequency']} · "
                f"баланс {signed_money(impact.get('money_delta', 0))} · "
                f"энергия −{impact.get('energy_cost', 0)} · время −{impact.get('time_cost', 0)} · "
                f"доверие −{impact.get('trust_cost', 0)}"
            )

            ctx = step.get("context", {})
            summary_parts = []
            if ctx.get("country_risk") == "high":
                summary_parts.append("⚠️ Высокий риск страны")
            if ctx.get("recipient_type") == "anonymous_wallet":
                summary_parts.append("🕵️ Анонимный кошелек")
            if ctx.get("time_of_day") == "night":
                summary_parts.append("🌙 Ночь")
            if ctx.get("velocity") == "rapid":
                summary_parts.append("⚡ Быстрый темп")
            if not ctx.get("has_documents", True):
                summary_parts.append("❌ Без документов")
            if summary_parts:
                st.caption(" | ".join(summary_parts))

            c_up, c_down, c_del = st.columns(3)
            with c_up:
                if st.button("⬆️", key=f"up_{idx}", disabled=idx == 0, use_container_width=True):
                    move_action = (idx, idx - 1)
            with c_down:
                if st.button("⬇️", key=f"down_{idx}", disabled=idx == len(steps) - 1, use_container_width=True):
                    move_action = (idx, idx + 1)
            with c_del:
                if st.button("🗑️", key=f"del_{idx}", use_container_width=True):
                    delete_idx = idx

    if move_action is not None:
        src, dst = move_action
        steps[src], steps[dst] = steps[dst], steps[src]
        st.session_state.draft_steps = steps
        st.rerun()

    if delete_idx is not None:
        steps.pop(delete_idx)
        st.session_state.draft_steps = steps
        st.rerun()

    st.markdown("---")
    c_s1, c_s2, c_s3 = st.columns(3)

    with c_s1:
        if st.button("💾 Сохранить черновик", use_container_width=True):
            try:
                res = client.put_scenario(
                    round_id,
                    steps,
                    st.session_state.expected_revision,
                    session_id,
                )
                st.session_state.expected_revision = res["revision"]
                st.session_state.server_scenario = res
                st.success(f"Черновик сохранен (ревизия #{res['revision']})!")
            except APIClientError as e:
                st.error(f"Ошибка сохранения: {e.message}")

    with c_s2:
        can_submit = resources["valid"] and resources["goal_reached"]
        if st.button("🚀 Отправить сценарий", type="primary", use_container_width=True, disabled=not can_submit):
            try:
                put_res = client.put_scenario(
                    round_id,
                    steps,
                    st.session_state.expected_revision,
                    session_id,
                )
                st.session_state.expected_revision = put_res["revision"]
                sub_res = client.submit_scenario(
                    round_id,
                    st.session_state.expected_revision,
                    session_id,
                )
                st.session_state.server_scenario = sub_res
                st.balloons()
                st.success("Сценарий успешно отправлен на скоринг!")
                st.switch_page(result_page)
            except APIClientError as e:
                st.error(f"Ошибка отправки: {e.message}")

    with c_s3:
        if st.button("🧹 Очистить", use_container_width=True):
            st.session_state.draft_steps = []
            st.rerun()


def render_result() -> None:
    client = get_api_client()
    session_id = st.session_state.session_id
    server_scen = st.session_state.server_scenario

    try:
        active_round = client.get_active_round()
    except Exception as e:
        st.error(f"Ошибка загрузки раунда: {e}")
        return

    if not active_round:
        st.info("Нет активного раунда.")
        return

    round_id = active_round["id"]
    render_page_header(
        "Результат раунда",
        "Решение AML-модели и Анализ",
        "Сравните оценку риска с затратами ресурсов и разберите признаки модели.",
    )

    try:
        res_data = client.get_result(round_id, session_id)
    except Exception as e:
        st.error(f"Ошибка получения результата: {e}")
        return

    if not res_data:
        if server_scen and server_scen.get("status") == "submitted":
            st.info(
                f"⏳ **Ваш сценарий (Ревизия #{server_scen.get('revision')}) успешно принят и зафиксирован в базе данных.**\n\n"
                "Ожидайте запуска общего скоринга организатором мастер-класса. После запуска здесь появится детальный разбор решения модели."
            )
            if st.button("🔄 Обновить статус", type="primary"):
                st.rerun()
            return
        else:
            st.info("Сценарий еще не отправлен на скоринг.")
            if st.button("Перейти в конструктор", type="primary"):
                st.switch_page(scenario_page)
            return

    base = res_data["base"]
    leaderboard_meta = res_data.get("leaderboard", {})
    explanation = res_data.get("explanation", {})

    label = base.get("risk_label", "normal")
    label_views = {
        "normal": ("Операция пропущена", "Низкий риск", "success"),
        "review": ("Назначена проверка", "Средний риск", "warning"),
        "suspicious": ("Сценарий заблокирован", "Высокий риск", "error"),
    }
    desc, risk_title, callout_type = label_views.get(label, ("Обработано", "Оценка", "info"))

    score_items = (
        ("Итоговый балл", f"{float(leaderboard_meta.get('effective_game_score', base.get('game_score', 0))):.1f} / 100", "main"),
        ("Риск модели", f"{float(base.get('risk_score', 0)):.1f} / 100", "detail"),
        ("Ресурсы", f"{float(base.get('resource_score', 0)):.1f} / 100", "detail"),
        ("Решение", desc, "detail"),
    )
    score_html = "".join(
        f'<div class="aml-score-{kind}"><div class="aml-score-label">{escape(label_txt)}</div>'
        f'<div class="aml-score-value">{escape(val)}</div></div>'
        for label_txt, val, kind in score_items
    )
    st.markdown(f'<div class="aml-score-hero">{score_html}</div>', unsafe_allow_html=True)
    getattr(st, callout_type)(f"**{risk_title}**. {desc}.")

    factors_tab, resources_tab, catboost_tab = st.tabs(
        ["🔍 Почему так решила модель", "💰 Ресурсы", "🤖 Вектор признаков CatBoost"]
    )

    with factors_tab:
        st.subheader("🚨 Главные факторы риска (Top Factors)")
        top_risks = explanation.get("top_risk_factors", [])
        if top_risks:
            for f in top_risks:
                st.warning(f"**+{f.get('points', 0)} баллов:** {f.get('description', '')}")
        else:
            st.info("Критических факторов риска не обнаружено.")

        st.subheader("🛡️ Защитные сигналы")
        protect = explanation.get("protective_factors", [])
        if protect:
            for f in protect:
                st.success(f"**{f.get('points', 0)} баллов:** {f.get('description', '')}")
        else:
            st.caption("Защитных факторов не зафиксировано.")

    with resources_tab:
        st.subheader("Сохраненные ресурсы")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Остаток баланса", format_money(float(base.get("remaining_balance", 0))))
        c2.metric("Остаток энергии", f"{int(base.get('remaining_energy', 0))} ед.")
        c3.metric("Остаток времени", f"{int(base.get('remaining_time', 0))} ч.")
        c4.metric("Уплачено комиссий", format_money(float(base.get("total_fees", 0))))

    with catboost_tab:
        cb_payload = explanation.get("catboost_features_payload", {})
        if cb_payload:
            render_catboost_features_inspector(cb_payload)
        else:
            st.info("Признаки CatBoost формируются при скоринге сценария.")


def render_leaderboard() -> None:
    client = get_api_client()
    session_id = st.session_state.session_id
    user = st.session_state.user

    try:
        active_round = client.get_active_round()
    except Exception as e:
        st.error(f"Ошибка загрузки раунда: {e}")
        return

    if not active_round:
        st.info("Нет активного раунда.")
        return

    round_id = active_round["id"]
    render_page_header(
        "Таблица лидеров",
        f"Рейтинг раунда #{round_id}",
        "Сравните свой результат с другими участниками мастер-класса.",
    )

    try:
        lb_data = client.get_leaderboard(round_id, session_id)
        rows = lb_data.get("rows", [])
    except Exception as e:
        st.error(f"Ошибка загрузки лидерборда: {e}")
        return

    if rows:
        df = pd.DataFrame(rows)
        df_display = df[["rank", "display_name", "game_score", "stealth_score", "resource_score", "risk_label"]].copy()
        df_display.columns = ["Место", "Участник", "Итоговый балл", "Скрытность (100−Риск)", "Ресурсы", "Оценка риска"]
        st.dataframe(df_display, hide_index=True, use_container_width=True)
    else:
        st.info("Лидерборд появится после завершения раунда и запуска скоринга администратором.")


# Navigation Setup
init_state()
client = get_api_client()

if not st.session_state.session_id or not st.session_state.user:
    login_screen(client)
    st.stop()

# Ensure scenario is loaded for the current user session
user = st.session_state.user
if st.session_state.loaded_user_id != user.get("id"):
    try:
        cur_round = client.get_active_round()
        if cur_round:
            sync_scenario_from_server(client, cur_round["id"], st.session_state.session_id, user["id"])
    except Exception:
        pass

# Define Navigation Pages
home_page = st.Page(render_home, title="Главная", icon=":material/home:", default=True)
scenario_page = st.Page(render_scenario, title="Сценарий", icon=":material/account_tree:")
result_page = st.Page(render_result, title="Результат", icon=":material/analytics:")
leaderboard_page = st.Page(render_leaderboard, title="Лидерборд", icon=":material/leaderboard:")

with st.sidebar:
    st.markdown(
        """
        <div class="aml-brand">
            <div class="aml-brand-title">AML Workshop Simulator</div>
            <div class="aml-brand-caption">Интерактивный симулятор финансовых цепочек</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="aml-player">
            <div class="aml-player-name">👤 {escape(user.get('display_name', 'Участник'))}</div>
            <div class="aml-player-email">{escape(user.get('email', ''))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Выйти из профиля", icon=":material/logout:", use_container_width=True):
        try:
            client.logout(st.session_state.session_id)
        except Exception:
            pass
        st.session_state.session_id = None
        st.session_state.user = None
        st.session_state.draft_steps = []
        st.session_state.server_scenario = None
        st.session_state.expected_revision = 0
        st.session_state.loaded_user_id = None
        st.rerun()

navigation = st.navigation(
    {
        "Игра": [home_page, scenario_page],
        "Раунд": [result_page, leaderboard_page],
    },
    position="sidebar",
)
navigation.run()
