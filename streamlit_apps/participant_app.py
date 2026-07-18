from __future__ import annotations

from html import escape
from uuid import uuid4

import pandas as pd
import streamlit as st

from backend.app.domain.action_parameters import (
    action_detail_summary,
    action_fields_for,
    context_fields_for,
    context_value_label,
    default_action_details,
    default_context,
    detail_factor_label,
    normalize_action_details,
)
from streamlit_apps.local_store import (
    ACTION_CARDS,
    INITIAL_BALANCE,
    INITIAL_ENERGY,
    INITIAL_TIME,
    INITIAL_TRUST,
    MAX_ACTIONS,
    MAX_IDENTICAL_STEPS,
    MAX_NIGHT_OPERATIONS,
    TARGET_OUTFLOW,
    get_store,
    resource_snapshot,
)


st.set_page_config(
    page_title="AML: игра против алгоритма",
    page_icon=":material/security:",
    layout="wide",
    initial_sidebar_state="auto",
)
st.markdown(
    """
    <style>
    :root {
        --aml-ink: var(--text-color);
        --aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
        --aml-line: color-mix(in srgb, var(--text-color) 18%, transparent);
        --aml-surface: var(--secondary-background-color);
        --aml-soft: color-mix(
            in srgb,
            var(--primary-color) 9%,
            var(--background-color)
        );
        --aml-primary: var(--primary-color);
        --aml-primary-dark: color-mix(
            in srgb,
            var(--primary-color) 78%,
            var(--text-color)
        );
        --aml-warning: var(--orange-color, #d89022);
        --aml-danger: var(--red-color, #d65353);
    }
    .block-container {
        max-width: 1180px;
        padding-top: 1.5rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid var(--aml-line);
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: .75rem;
    }
    [data-testid="stMetric"] {
        min-height: 88px;
        padding: .8rem .9rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    [data-testid="stMetricLabel"] {color: var(--aml-muted);}
    [data-testid="stMetricValue"] {font-size: 23px;}
    [data-testid="stForm"] {
        padding: 1.1rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    h1, h2, h3, p {letter-spacing: 0;}
    h1 {font-size: 34px; margin-bottom: .35rem;}
    h2 {font-size: 22px;}
    h3 {font-size: 18px;}
    .aml-kicker {
        margin-bottom: .35rem;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0;
        text-transform: uppercase;
        color: var(--aml-primary);
    }
    .aml-page-title {
        margin: 0 0 .35rem;
        font-size: 34px !important;
        line-height: 1.15 !important;
        overflow-wrap: anywhere;
    }
    .aml-subtitle {
        max-width: 780px;
        margin: 0 0 1.25rem;
        color: var(--aml-muted);
        font-size: 16px;
    }
    .aml-brand {
        padding: .35rem 0 .8rem;
        border-bottom: 1px solid var(--aml-line);
    }
    .aml-brand-title {font-size: 17px; font-weight: 700; color: var(--aml-ink);}
    .aml-brand-caption {margin-top: .2rem; font-size: 12px; color: var(--aml-muted);}
    .aml-player {
        padding: .75rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    .aml-player-name {font-weight: 700; color: var(--aml-ink);}
    .aml-player-email {
        overflow: hidden;
        margin-top: .15rem;
        color: var(--aml-muted);
        font-size: 12px;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .aml-sync {
        padding: .65rem .75rem;
        border-left: 3px solid var(--aml-warning);
        background: color-mix(
            in srgb,
            var(--aml-warning) 14%,
            var(--background-color)
        );
        color: var(--aml-ink);
        font-size: 13px;
    }
    .aml-resource-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: .65rem;
        margin: .9rem 0 .55rem;
    }
    .aml-resource {
        min-width: 0;
        padding: .8rem .85rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    .aml-resource-label {font-size: 12px; color: var(--aml-muted);}
    .aml-resource-value {
        overflow-wrap: anywhere;
        margin: .12rem 0 .42rem;
        font-size: 18px;
        font-weight: 700;
        color: var(--aml-ink);
    }
    .aml-resource-note {font-size: 12px; color: var(--aml-muted);}
    .aml-bar {
        height: 4px;
        margin: .45rem 0 .35rem;
        background: color-mix(in srgb, var(--text-color) 12%, transparent);
    }
    .aml-bar > span {display: block; height: 100%; background: var(--aml-primary);}
    .aml-resource[data-tone="warning"] .aml-bar > span {background: var(--aml-warning);}
    .aml-resource[data-tone="danger"] .aml-bar > span {background: var(--aml-danger);}
    .aml-resource-footer {
        display: flex;
        flex-wrap: wrap;
        gap: .35rem 1rem;
        color: var(--aml-muted);
        font-size: 12px;
    }
    .aml-progress-steps {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        margin: 1.1rem 0 1.5rem;
        border-top: 1px solid var(--aml-line);
        border-bottom: 1px solid var(--aml-line);
    }
    .aml-progress-step {padding: .75rem .8rem; color: var(--aml-muted);}
    .aml-progress-step + .aml-progress-step {border-left: 1px solid var(--aml-line);}
    .aml-progress-step strong {display: block; color: var(--aml-ink);}
    .aml-progress-step[data-state="done"] strong {color: var(--aml-primary);}
    .aml-progress-step[data-state="current"] {background: var(--aml-soft);}
    .aml-progress-index {font-size: 12px; color: var(--aml-muted);}
    .aml-card-specs, .aml-impact-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .45rem;
        margin: .7rem 0 1rem;
    }
    .aml-spec, .aml-impact {
        min-width: 0;
        padding: .55rem .6rem;
        border-top: 2px solid var(--aml-line);
        background: color-mix(
            in srgb,
            var(--secondary-background-color) 88%,
            var(--text-color)
        );
    }
    .aml-spec span, .aml-impact span {display: block; font-size: 11px; color: var(--aml-muted);}
    .aml-spec strong, .aml-impact strong {
        display: block;
        margin-top: .12rem;
        overflow-wrap: anywhere;
        font-size: 13px;
        color: var(--aml-ink);
    }
    .aml-impact {border-top-color: var(--aml-primary);}
    .aml-step-label {font-size: 12px; color: var(--aml-muted); margin-bottom: .15rem;}
    .aml-score-hero {
        display: grid;
        grid-template-columns: minmax(180px, 1.25fr) repeat(3, minmax(120px, 1fr));
        gap: .65rem;
        margin: 1rem 0;
    }
    .aml-score-main, .aml-score-detail {
        padding: .9rem 1rem;
        border: 1px solid var(--aml-line);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    .aml-score-main {border-top: 3px solid var(--aml-primary);}
    .aml-score-label {font-size: 12px; color: var(--aml-muted);}
    .aml-score-value {margin-top: .15rem; font-size: 26px; font-weight: 700; color: var(--aml-ink);}
    .aml-score-detail .aml-score-value {font-size: 18px;}
    .aml-podium {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: .65rem;
        margin: .8rem 0 1rem;
    }
    .aml-podium-item {
        min-width: 0;
        padding: .85rem;
        border: 1px solid var(--aml-line);
        border-top: 3px solid var(--aml-primary);
        border-radius: 6px;
        background: var(--aml-surface);
    }
    .aml-podium-rank {font-size: 12px; color: var(--aml-muted);}
    .aml-podium-name {overflow-wrap: anywhere; margin: .18rem 0; font-weight: 700;}
    .aml-podium-score {font-size: 22px; font-weight: 700; color: var(--aml-primary-dark);}
    .aml-podium-meta {font-size: 12px; color: var(--aml-muted);}
    @media (max-width: 900px) {
        .block-container {padding-top: 1rem; padding-left: 1rem; padding-right: 1rem;}
        .aml-resource-grid {grid-template-columns: repeat(3, minmax(0, 1fr));}
        .aml-score-hero {grid-template-columns: repeat(2, minmax(0, 1fr));}
    }
    @media (max-width: 600px) {
        h1 {font-size: 30px;}
        .aml-page-title {font-size: 30px !important;}
        .block-container {padding-left: .85rem; padding-right: .85rem;}
        .aml-resource-grid {grid-template-columns: repeat(2, minmax(0, 1fr));}
        .aml-resource:last-child {grid-column: 1 / -1;}
        .aml-progress-steps {grid-template-columns: 1fr;}
        .aml-progress-step + .aml-progress-step {
            border-top: 1px solid var(--aml-line);
            border-left: 0;
        }
        .aml-card-specs, .aml-impact-grid {grid-template-columns: repeat(2, minmax(0, 1fr));}
        .aml-score-hero, .aml-podium {grid-template-columns: 1fr;}
        [data-testid="stMetric"] {min-height: 78px;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

store = get_store()

GEO_LABELS = {"Низкий": "low", "Средний": "medium", "Высокий": "high"}
RECIPIENT_LABELS = {
    "Знакомый": "known_counterparty",
    "Новый": "new_counterparty",
    "Анонимный кошелек": "anonymous_wallet",
}
TIME_LABELS = {"День": "day", "Вечер": "evening", "Ночь": "night"}
VELOCITY_LABELS = {
    "С интервалами": "spaced",
    "Обычный темп": "normal",
    "Быстро подряд": "rapid",
}
CHANNEL_LABELS = {
    "bank": "Банковское зачисление",
    "branch": "Отделение",
    "mobile": "Мобильное приложение",
    "web": "Веб-кабинет",
    "atm": "Банкомат",
    "exchange": "Криптобиржа",
}


def initialize_state() -> None:
    defaults = {"user": None, "draft_steps": []}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="aml-kicker">{escape(kicker)}</div>
        <h1 class="aml-page-title">{escape(title)}</h1>
        <p class="aml-subtitle">{escape(subtitle)}</p>
        """,
        unsafe_allow_html=True,
    )


def render_round_progress(scenario: dict | None) -> None:
    scenario_state = scenario["status"] if scenario else "draft"
    states = {
        "draft": ("current", "todo", "todo"),
        "submitted": ("done", "current", "todo"),
        "scored": ("done", "done", "current"),
    }[scenario_state]
    labels = (
        ("01", "Соберите", "Черновик сценария"),
        ("02", "Отправьте", "Проверка ограничений"),
        ("03", "Сравните", "Результат и рейтинг"),
    )
    items = "".join(
        (
            f'<div class="aml-progress-step" data-state="{state}">'
            f'<span class="aml-progress-index">{index}</span>'
            f"<strong>{title}</strong><span>{caption}</span></div>"
        )
        for state, (index, title, caption) in zip(states, labels, strict=True)
    )
    st.markdown(f'<div class="aml-progress-steps">{items}</div>', unsafe_allow_html=True)


def login_screen() -> None:
    _, center, _ = st.columns([1, 1.25, 1])
    with center:
        render_page_header(
            "AML Simulator · локальный раунд",
            "Обойди алгоритм",
            "Соберите финансовый маршрут, сохраните ресурсы и разберите "
            "сигналы учебной AML-модели.",
        )
        login_tab, register_tab = st.tabs(["Вход", "Регистрация"])
        with login_tab:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="name@example.com")
                password = st.text_input("Пароль", type="password")
                submitted = st.form_submit_button(
                    "Войти", type="primary", width="stretch"
                )
            if submitted:
                try:
                    st.session_state.user = store.login(email, password)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with register_tab:
            with st.form("register_form"):
                name = st.text_input(
                    "Имя на общей доске",
                    placeholder="Например, Финансовый детектив",
                )
                email = st.text_input(
                    "Email", placeholder="name@example.com", key="register_email"
                )
                password = st.text_input(
                    "Придумайте пароль", type="password", key="register_password"
                )
                submitted = st.form_submit_button(
                    "Создать профиль", type="primary", width="stretch"
                )
            if submitted:
                try:
                    st.session_state.user = store.register(name, email, password)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        st.markdown(
            """
            <div class="aml-sync">
                Локальный режим: профили и результаты сохраняются до перезапуска приложения.
                В сетевой версии здесь будет отображаться синхронизация раунда.
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_resource_dashboard(resources: dict) -> None:
    items = (
        (
            "Деньги",
            format_money(resources["balance"]),
            signed_money(resources["balance"] - INITIAL_BALANCE),
            clamp_ratio(resources["balance"], INITIAL_BALANCE),
        ),
        (
            "Энергия",
            f"{resources['energy']} / {INITIAL_ENERGY}",
            "запас действий",
            clamp_ratio(resources["energy"], INITIAL_ENERGY),
        ),
        (
            "Время",
            f"{resources['time']} / {INITIAL_TIME}",
            "до лимита раунда",
            clamp_ratio(resources["time"], INITIAL_TIME),
        ),
        (
            "Доверие",
            f"{resources['trust']} / {INITIAL_TRUST}",
            "профиль клиента",
            clamp_ratio(resources["trust"], INITIAL_TRUST),
        ),
        (
            "Проведено",
            format_money(resources["outflow"]),
            f"цель {format_money(TARGET_OUTFLOW)}",
            clamp_ratio(resources["outflow"], TARGET_OUTFLOW),
        ),
    )
    cards = []
    for label, value, note, ratio in items:
        tone = "danger" if ratio < 0.2 else "warning" if ratio < 0.45 else "normal"
        cards.append(
            f'<div class="aml-resource" data-tone="{tone}">'
            f'<div class="aml-resource-label">{escape(label)}</div>'
            f'<div class="aml-resource-value">{escape(value)}</div>'
            f'<div class="aml-bar"><span style="width:{ratio * 100:.1f}%"></span></div>'
            f'<div class="aml-resource-note">{escape(note)}</div></div>'
        )
    st.markdown(
        '<div class="aml-resource-grid">'
        + "".join(cards)
        + '</div><div class="aml-resource-footer">'
        + f"<span>Действия: {resources['slots']} из {MAX_ACTIONS} свободно</span>"
        + f"<span>Комиссии: {escape(format_money(resources['fees']))}</span>"
        + f"<span>Эффективность: {resources['resource_score']:.1f} / 100</span>"
        + "</div>",
        unsafe_allow_html=True,
    )


def render_round_limits(resources: dict) -> None:
    rows = []
    for item in resources["limits"]:
        rows.append(
            {
                "Квота": item["label"],
                "Использовано": format_money(item["used"]),
                "Лимит": format_money(item["limit"]),
                "Осталось": format_money(item["remaining"]),
                "Статус": "Превышен" if item["used"] > item["limit"] else "В норме",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        f"Дополнительно: не более {MAX_NIGHT_OPERATIONS} ночных операций и "
        f"не более {MAX_IDENTICAL_STEPS} одинаковых шагов подряд."
    )


def render_home() -> None:
    user = st.session_state.user
    scenario = store.get_scenario(user["id"])
    render_page_header(
        "Раунд 1 · учебная модель",
        f"Добро пожаловать, {user['name']}",
        "Проведите нужный оборот, сохраните ресурсы и сравните свой маршрут "
        "с решениями других игроков.",
    )
    render_round_progress(scenario)

    task_col, rating_col = st.columns([1.35, 1], gap="large")
    with task_col:
        st.subheader("Игровая задача")
        st.write(
            f"Проведите не менее {format_money(TARGET_OUTFLOW)} через расходные "
            f"операции максимум за {MAX_ACTIONS} действий. Баланс, энергия, время "
            "и доверие не должны опуститься ниже нуля."
        )
        goal_col, balance_col, status_col = st.columns(3)
        goal_col.metric("Цель", format_money(TARGET_OUTFLOW))
        balance_col.metric("Баланс", format_money(INITIAL_BALANCE))
        status_col.metric(
            "Сценарий",
            "Черновик" if scenario is None else scenario_status(scenario),
        )
    with rating_col:
        st.subheader("Формула рейтинга")
        st.write(
            "60% итогового балла дает незаметность для модели. Остальные 40% "
            "зависят от сохраненных ресурсов, комиссий и числа действий."
        )
        st.progress(0.6, text="Незаметность · 60%")
        st.progress(0.4, text="Эффективность · 40%")

    st.divider()
    action_col, board_col = st.columns([2, 1])
    if action_col.button(
        "Собрать сценарий",
        type="primary",
        icon=":material/arrow_forward:",
        width="stretch",
    ):
        st.switch_page(scenario_page)
    if board_col.button(
        "Открыть рейтинг",
        icon=":material/leaderboard:",
        width="stretch",
    ):
        st.switch_page(leaderboard_page)


def render_scenario() -> None:
    sync_draft_from_widgets()
    steps = st.session_state.draft_steps
    resources = resource_snapshot(steps)

    render_page_header(
        "Конструктор сценария",
        "Соберите финансовый маршрут",
        "Добавляйте операции слева и сразу проверяйте порядок шагов, ресурсы "
        "и ограничения раунда справа.",
    )
    render_resource_dashboard(resources)
    with st.expander("Квоты и жесткие ограничения"):
        render_round_limits(resources)

    st.markdown("---")
    builder_col, sequence_col = st.columns([1.05, 0.95], gap="large")
    with builder_col:
        render_action_builder(steps)
    with sequence_col:
        render_scenario_steps(steps)


def render_scenario_steps(steps: list[dict]) -> None:
    title_col, counter_col = st.columns([4, 1])
    title_col.subheader("Цепочка операций")
    counter_col.caption(f"{len(steps)} из {MAX_ACTIONS} действий")
    if not steps:
        st.info(
            "Цепочка пока пуста. Настройте и добавьте первую операцию.",
            icon=":material/touch_app:",
        )
        return

    delete_uid = None
    move_action = None
    current_resources = resource_snapshot(steps)
    card_lookup = {card["code"]: card for card in ACTION_CARDS}
    for index, step in enumerate(steps):
        card = card_lookup[step["card_code"]]
        impact = current_resources["steps"][index]
        with st.container(border=True):
            st.markdown(f"**{index + 1}. {card['icon']} {card['title']}**")
            st.caption(
                f"{format_money(step['amount'])} × {step['frequency']} · "
                f"баланс {signed_money(impact['money_delta'])} · "
                f"энергия −{impact['energy_cost']} · время −{impact['time_cost']} · "
                f"доверие −{impact['trust_cost']}"
            )
            st.caption(step_parameter_summary(step))
            up_col, down_col, delete_col = st.columns(3)
            if up_col.button(
                "",
                key=f"up_{step['uid']}",
                icon=":material/arrow_upward:",
                disabled=index == 0,
                help="Переместить выше",
                width="stretch",
            ):
                move_action = (index, index - 1)
            if down_col.button(
                "",
                key=f"down_{step['uid']}",
                icon=":material/arrow_downward:",
                disabled=index == len(steps) - 1,
                help="Переместить ниже",
                width="stretch",
            ):
                move_action = (index, index + 1)
            if delete_col.button(
                "",
                key=f"delete_{step['uid']}",
                icon=":material/delete:",
                help="Удалить",
                width="stretch",
            ):
                delete_uid = step["uid"]
            render_step_editor(step, card)

    if delete_uid:
        st.session_state.draft_steps = [
            step for step in steps if step["uid"] != delete_uid
        ]
        st.rerun()
    if move_action:
        source, target = move_action
        steps[source], steps[target] = steps[target], steps[source]
        st.rerun()

    resources = resource_snapshot(steps)
    if resources["violations"]:
        st.error(resources["violations"][0], icon=":material/error:")
        with st.expander(f"Все нарушения ({len(resources['violations'])})"):
            for violation in resources["violations"]:
                st.write(f"- {violation}")
    elif not resources["goal_reached"]:
        remaining = TARGET_OUTFLOW - resources["outflow"]
        st.info(
            f"До цели раунда осталось провести {format_money(remaining)}.",
            icon=":material/flag:",
        )
    else:
        st.success(
            "Цель достигнута, квоты соблюдены. Сценарий можно отправлять.",
            icon=":material/check_circle:",
        )

    st.caption("Повторная отправка заменит предыдущий сценарий до начала скоринга.")
    submit_col, clear_col = st.columns([2.2, 1])
    ready_to_submit = resources["valid"] and resources["goal_reached"]
    if submit_col.button(
        "Отправить сценарий",
        type="primary",
        icon=":material/send:",
        width="stretch",
        disabled=not ready_to_submit,
    ):
        clean_steps = [
            {key: value for key, value in step.items() if key != "uid"}
            for step in st.session_state.draft_steps
        ]
        store.submit(st.session_state.user["id"], clean_steps)
        st.switch_page(result_page)
    if clear_col.button(
        "",
        icon=":material/delete_sweep:",
        help="Очистить сценарий",
        width="stretch",
    ):
        st.session_state.draft_steps = []
        st.rerun()


def render_field_grid(
    fields: tuple[dict, ...],
    key_prefix: str,
    current_values: dict,
) -> dict:
    values: dict = {}
    for offset in range(0, len(fields), 2):
        pair = fields[offset : offset + 2]
        columns = st.columns(len(pair))
        for column, field in zip(columns, pair, strict=True):
            key = field["key"]
            current = current_values.get(key, field["default"])
            with column:
                if field["kind"] == "toggle":
                    values[key] = st.toggle(
                        field["label"],
                        value=bool(current),
                        key=f"{key_prefix}_{key}",
                        help=field.get("help"),
                    )
                    continue
                option_labels = {
                    option["value"]: option["label"]
                    for option in field["options"]
                }
                options = list(option_labels)
                if current not in options:
                    current = field["default"]
                values[key] = st.selectbox(
                    field["label"],
                    options,
                    index=options.index(current),
                    format_func=lambda value, labels=option_labels: labels[value],
                    key=f"{key_prefix}_{key}",
                    help=field.get("help"),
                )
    return values


def render_parameter_fields(
    card_code: str,
    key_prefix: str,
    context_values: dict | None = None,
    detail_values: dict | None = None,
) -> tuple[dict, dict]:
    context_current = default_context(card_code)
    context_current.update(context_values or {})
    details_current = normalize_action_details(card_code, detail_values)

    context_fields = context_fields_for(card_code)
    if context_fields:
        st.markdown("**Обстоятельства операции**")
    rendered_context = render_field_grid(
        context_fields,
        f"{key_prefix}_context",
        context_current,
    )

    action_fields = action_fields_for(card_code)
    if action_fields:
        st.markdown("**Параметры выбранного действия**")
    rendered_details = render_field_grid(
        action_fields,
        f"{key_prefix}_detail",
        details_current,
    )
    return rendered_context, rendered_details


def render_action_builder(steps: list[dict]) -> None:
    st.subheader("Настройка операции")
    card_lookup = {card["code"]: card for card in ACTION_CARDS}
    selected_code = st.selectbox(
        "Тип операции",
        options=list(card_lookup),
        format_func=lambda code: (
            f"{card_lookup[code]['title']} · {card_lookup[code]['category']}"
        ),
    )
    card = card_lookup[selected_code]
    st.caption(card["description"])

    specs = (
        ("Сумма", f"{format_money(card['min_amount'])} - {format_money(card['max_amount'])}"),
        ("Повторы", f"до {card['max_frequency']} за шаг"),
        ("Ресурсы", f"{card['energy_cost']} эн. · {card['time_cost']} вр."),
        ("Комиссия", f"{card['fee_rate'] * 100:g}%"),
    )
    spec_html = "".join(
        f'<div class="aml-spec"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in specs
    )
    st.markdown(f'<div class="aml-card-specs">{spec_html}</div>', unsafe_allow_html=True)

    basic_tab, context_tab = st.tabs(["Операция", "Контекст"])
    with basic_tab:
        amount_col, frequency_col = st.columns([1.55, 0.85])
        amount = amount_col.number_input(
            "Сумма одного платежа, ₽",
            min_value=card["min_amount"],
            max_value=card["max_amount"],
            value=min(50_000, card["max_amount"]),
            step=5_000,
            key=f"new_amount_{selected_code}",
        )
        frequency = frequency_col.number_input(
            "Повторов",
            min_value=1,
            max_value=card["max_frequency"],
            value=1,
            key=f"new_frequency_{selected_code}",
        )
        channel = st.selectbox(
            "Канал",
            card["channels"],
            format_func=lambda value: CHANNEL_LABELS[value],
            key=f"new_channel_{selected_code}",
        )
    with context_tab:
        context_values, detail_values = render_parameter_fields(
            selected_code,
            f"new_{selected_code}",
        )

    proposed_step = new_step(
        selected_code,
        amount=int(amount),
        frequency=int(frequency),
        country_risk=context_values.get("country_risk", "low"),
        recipient_type=context_values.get("recipient_type", "known_counterparty"),
        time_of_day=context_values.get("time_of_day", "day"),
        velocity=context_values.get("velocity", "normal"),
        channel=channel,
        has_documents=bool(context_values.get("has_documents", True)),
        details=detail_values,
    )
    proposed_resources = resource_snapshot([*steps, proposed_step])
    proposed_impact = proposed_resources["steps"][-1]
    impacts = (
        ("Баланс", signed_money(proposed_impact["money_delta"])),
        ("Энергия", f"−{proposed_impact['energy_cost']}"),
        ("Время", f"−{proposed_impact['time_cost']}"),
        ("Доверие", f"−{proposed_impact['trust_cost']}"),
    )
    impact_html = "".join(
        f'<div class="aml-impact"><span>{escape(label)}</span>'
        f"<strong>{escape(value)}</strong></div>"
        for label, value in impacts
    )
    st.markdown(
        '<div class="aml-step-label">Влияние нового шага</div>'
        f'<div class="aml-impact-grid">{impact_html}</div>',
        unsafe_allow_html=True,
    )
    cannot_add = len(steps) >= MAX_ACTIONS or not proposed_resources["valid"]
    if st.button(
        "Добавить в цепочку",
        type="primary",
        icon=":material/add:",
        width="stretch",
        disabled=cannot_add,
    ):
        steps.append(proposed_step)
        st.rerun()
    if cannot_add:
        reason = (
            f"Достигнут лимит: {MAX_ACTIONS} действий."
            if len(steps) >= MAX_ACTIONS
            else proposed_resources["violations"][0]
        )
        st.warning(reason, icon=":material/block:")


def render_step_editor(step: dict, card: dict) -> None:
    with st.expander("Изменить параметры"):
        operation_tab, context_tab = st.tabs(["Операция", "Контекст"])
        with operation_tab:
            amount_col, frequency_col = st.columns([1.55, 0.85])
            step["amount"] = amount_col.number_input(
                "Сумма, ₽",
                min_value=card["min_amount"],
                max_value=card["max_amount"],
                step=5_000,
                value=int(step["amount"]),
                key=f"step_{step['uid']}_amount",
            )
            step["frequency"] = frequency_col.number_input(
                "Повторов",
                min_value=1,
                max_value=card["max_frequency"],
                value=int(step["frequency"]),
                key=f"step_{step['uid']}_frequency",
            )
            channel_options = card["channels"]
            channel_value = step.get("channel", channel_options[0])
            step["channel"] = st.selectbox(
                "Канал",
                channel_options,
                index=channel_options.index(channel_value),
                format_func=lambda value: CHANNEL_LABELS[value],
                key=f"step_{step['uid']}_channel",
            )
        with context_tab:
            context_values, detail_values = render_parameter_fields(
                card["code"],
                f"step_{step['uid']}",
                context_values=step,
                detail_values=step.get("details"),
            )
            step.update(context_values)
            step["details"] = detail_values


def render_result() -> None:
    scenario = store.get_scenario(st.session_state.user["id"])
    render_page_header(
        "Результат раунда",
        "Решение AML-модели",
        "Сравните оценку риска с затратами ресурсов и разберите признаки, "
        "которые повлияли на решение.",
    )
    render_round_progress(scenario)
    if scenario is None:
        st.info("Сначала соберите и отправьте сценарий.", icon=":material/info:")
        if st.button(
            "Перейти в конструктор",
            type="primary",
            icon=":material/account_tree:",
        ):
            st.switch_page(scenario_page)
        return
    if scenario["result"] is None:
        st.status(
            "Сценарий принят и зафиксирован. Ожидаем общий скоринг раунда.",
            state="running",
        )
        st.caption(
            "В целевой версии результат появится автоматически после команды "
            "администратора; локальный MVP использует демо-управление ниже."
        )
        render_scoring_controls("result")
        render_sequence_summary(scenario["steps"])
        return

    result = scenario["result"]
    label_view = {
        "normal": ("Операция пропущена", "Низкий риск", "success"),
        "review": ("Назначена проверка", "Средний риск", "warning"),
        "suspicious": ("Сценарий заблокирован", "Высокий риск", "error"),
    }[result["label"]]
    score_items = (
        ("Игровой балл", f"{result['game_score']:.1f} / 100", "main"),
        ("Риск модели", f"{result['risk_score']:.1f} / 100", "detail"),
        ("Ресурсы", f"{result['resource_score']:.1f} / 100", "detail"),
        ("Решение", label_view[0], "detail"),
    )
    score_html = "".join(
        f'<div class="aml-score-{kind}"><div class="aml-score-label">{escape(label)}</div>'
        f'<div class="aml-score-value">{escape(value)}</div></div>'
        for label, value, kind in score_items
    )
    st.markdown(f'<div class="aml-score-hero">{score_html}</div>', unsafe_allow_html=True)
    getattr(st, label_view[2])(
        f"{label_view[1]}. Игровой балл учитывает незаметность и эффективность ресурсов."
    )

    factors_tab, resources_tab, sequence_tab = st.tabs(
        ["Почему так решила модель", "Ресурсы", "Отправленная цепочка"]
    )
    with factors_tab:
        render_factor_explanation(result["explanation"])
    with resources_tab:
        render_resource_result(result)
    with sequence_tab:
        render_sequence_summary(scenario["steps"])


def render_factor_explanation(explanation: dict) -> None:
    st.subheader("Главные факторы риска")
    risk_rows = [factor_row(factor) for factor in explanation["top_factors"]]
    if risk_rows:
        chart_data = pd.DataFrame(risk_rows)
        st.bar_chart(
            chart_data,
            x="Признак",
            y="Вклад",
            horizontal=True,
            width="stretch",
        )
    else:
        st.info("Положительных факторов риска не найдено.")

    st.subheader("Защитные сигналы")
    protective_rows = [
        factor_row(factor) for factor in explanation.get("protective_factors", [])
    ]
    if protective_rows:
        st.dataframe(pd.DataFrame(protective_rows), hide_index=True, width="stretch")
    else:
        st.caption("В сценарии нет факторов, снижающих риск.")

    with st.expander("Все признаки модели"):
        all_rows = [factor_row(factor) for factor in explanation["all_factors"]]
        st.dataframe(pd.DataFrame(all_rows), hide_index=True, width="stretch")
    st.caption(explanation["note"])


def render_resource_result(result: dict) -> None:
    resources = result["resources"]
    render_resource_dashboard(resources)
    st.info(
        f"Незаметность: {result['stealth_score']:.1f} × 60% + "
        f"ресурсы: {result['resource_score']:.1f} × 40% = "
        f"{result['game_score']:.1f} балла."
    )
    render_round_limits(resources)


def render_leaderboard() -> None:
    scenario = store.get_scenario(st.session_state.user["id"])
    render_page_header(
        "Общий результат",
        "Лидерборд раунда",
        "Позиция учитывает незаметность сценария и эффективность использования ресурсов.",
    )
    render_round_progress(scenario)
    counts = store.status_counts()
    reg_col, submitted_col, scored_col = st.columns(3)
    reg_col.metric("Игроков", counts["registered"])
    submitted_col.metric("Отправили", counts["submitted"])
    scored_col.metric("Оценено", counts["scored"])
    render_scoring_controls("leaderboard")

    rows = store.leaderboard()
    if not rows:
        st.info("В рейтинге пока нет оцененных сценариев.")
        return

    current = next(
        (row for row in rows if row["user_id"] == st.session_state.user["id"]),
        None,
    )
    if current:
        st.success(
            f"Ваше место: {current['rank']} из {len(rows)} · "
            f"{current['game_score']:.1f} балла",
            icon=":material/emoji_events:",
        )

    podium = rows[:3]
    podium_html = "".join(
        (
            '<div class="aml-podium-item">'
            f'<div class="aml-podium-rank">{row["rank"]} место</div>'
            f'<div class="aml-podium-name">{escape(row["name"])}</div>'
            f'<div class="aml-podium-score">{row["game_score"]:.1f}</div>'
            f'<div class="aml-podium-meta">риск {row["risk_score"]:.1f} · '
            f'ресурсы {row["resource_score"]:.1f}</div></div>'
        )
        for row in podium
    )
    st.markdown(f'<div class="aml-podium">{podium_html}</div>', unsafe_allow_html=True)

    table_rows = []
    for row in rows:
        table_rows.append(
            {
                "Место": row["rank"],
                "Игрок": row["name"],
                "Игровой балл": row["game_score"],
                "Незаметность": row["stealth_score"],
                "Ресурсы": row["resource_score"],
                "Риск модели": row["risk_score"],
            }
        )
    st.dataframe(pd.DataFrame(table_rows), hide_index=True, width="stretch")
    with st.expander("Подробные ресурсы игроков"):
        resource_rows = [
            {
                "Игрок": row["name"],
                "Деньги": format_money(row["balance"]),
                "Энергия": row["energy"],
                "Время": row["time"],
                "Доверие": row["trust"],
                "Комиссии": format_money(row["fees"]),
            }
            for row in rows
        ]
        st.dataframe(
            pd.DataFrame(resource_rows),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "При равенстве игрового балла выше находится сценарий с меньшим риском, "
        "затем с лучшей эффективностью ресурсов и более ранней отправкой."
    )


def render_scoring_controls(key_prefix: str) -> None:
    with st.expander("Управление раундом (демо)"):
        st.caption("В автономном MVP эта кнопка имитирует команду администратора.")
        if st.button(
            "Оценить все отправленные сценарии",
            type="primary",
            key=f"score_all_{key_prefix}",
        ):
            count = store.score_all()
            st.success(f"Оценено сценариев: {count}")
            st.rerun()


def factor_row(factor: dict) -> dict:
    return {
        "Шаг": factor["step"] if factor["step"] else "Вся цепочка",
        "Признак": factor_name(factor["name"]),
        "Вклад": factor["points"],
        "Объяснение": factor.get("description", ""),
    }


def factor_name(raw_name: str) -> str:
    if raw_name.startswith("card:"):
        code = raw_name.split(":", 1)[1]
        card = next((card for card in ACTION_CARDS if card["code"] == code), None)
        return f"Тип операции: {card['title'] if card else code}"
    if raw_name.startswith("country_risk:"):
        value = raw_name.split(":", 1)[1]
        return f"Риск страны: {label_for(GEO_LABELS, value)}"
    if raw_name.startswith("recipient:"):
        value = raw_name.split(":", 1)[1]
        return f"Получатель: {label_for(RECIPIENT_LABELS, value)}"
    if raw_name.startswith("time_of_day:"):
        value = raw_name.split(":", 1)[1]
        return f"Время: {label_for(TIME_LABELS, value)}"
    if raw_name.startswith("velocity:"):
        value = raw_name.split(":", 1)[1]
        return f"Темп: {label_for(VELOCITY_LABELS, value)}"
    if raw_name.startswith("channel:"):
        value = raw_name.split(":", 1)[1]
        return f"Канал: {CHANNEL_LABELS.get(value, value)}"
    if raw_name.startswith("detail:"):
        _, card_code, field_key, value = raw_name.split(":", 3)
        return detail_factor_label(card_code, field_key, value)
    names = {
        "amount": "Сумма операции",
        "frequency": "Частота повторов",
        "documents": "Подтверждающие документы",
        "sequence:repeated_amounts": "Повторяющиеся суммы",
        "sequence:rapid_turnover": "Быстрый вывод поступления",
        "sequence:cash_to_high_risk": "Наличные в высокорисковый канал",
    }
    return names.get(raw_name, raw_name)


def render_sequence_summary(steps: list[dict]) -> None:
    resources = resource_snapshot(steps)
    render_resource_dashboard(resources)
    card_lookup = {card["code"]: card for card in ACTION_CARDS}
    cols = st.columns(min(4, len(steps)))
    for index, step in enumerate(steps):
        card = card_lookup[step["card_code"]]
        impact = resources["steps"][index]
        with cols[index % len(cols)].container(border=True):
            st.markdown(
                f'<div class="aml-step">Шаг {index + 1}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**{card['title']}**")
            st.caption(
                f"{format_money(step['amount'])} · {step['frequency']} раз(а) · "
                f"{CHANNEL_LABELS.get(step.get('channel', ''), 'Канал не указан')}"
            )
            st.caption(step_parameter_summary(step, include_channel=False))
            st.caption(
                f"Энергия −{impact['energy_cost']} · время −{impact['time_cost']} · "
                f"доверие −{impact['trust_cost']}"
            )


def scenario_status(scenario: dict | None) -> str:
    if scenario is None:
        return "Не отправлен"
    return "Оценен" if scenario["status"] == "scored" else "Ожидает скоринга"


def format_money(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{format_money(abs(value))}"


def clamp_ratio(value: float, maximum: float) -> float:
    return max(0.0, min(1.0, value / maximum))


def label_for(mapping: dict[str, str], value: str) -> str:
    return next(
        (label for label, mapped_value in mapping.items() if mapped_value == value),
        value,
    )


def step_parameter_summary(step: dict, include_channel: bool = True) -> str:
    card_code = step["card_code"]
    parts = []
    if include_channel:
        parts.append(CHANNEL_LABELS.get(step.get("channel", ""), "Канал не указан"))
    parts.extend(
        f"{item['label']}: {item['value']}"
        for item in action_detail_summary(card_code, step.get("details"))[:2]
    )
    context_priority = ("country_risk", "recipient_type", "time_of_day")
    available_context = {
        field["key"]: field for field in context_fields_for(card_code)
    }
    for field_key in context_priority:
        if field_key not in available_context:
            continue
        field = available_context[field_key]
        parts.append(
            context_value_label(field_key, step.get(field_key, field["default"]))
        )
        if len(parts) >= 5:
            break
    return " · ".join(parts) or "Параметры по умолчанию"


def sync_draft_from_widgets() -> None:
    for step in st.session_state.draft_steps:
        uid = step["uid"]
        for field in ("amount", "frequency", "channel"):
            key = f"step_{uid}_{field}"
            if key in st.session_state:
                step[field] = st.session_state[key]
        for field in context_fields_for(step["card_code"]):
            key = f"step_{uid}_context_{field['key']}"
            if key in st.session_state:
                step[field["key"]] = st.session_state[key]
        details = normalize_action_details(step["card_code"], step.get("details"))
        for field in action_fields_for(step["card_code"]):
            key = f"step_{uid}_detail_{field['key']}"
            if key in st.session_state:
                details[field["key"]] = st.session_state[key]
        step["details"] = details


def new_step(
    card_code: str,
    amount: int = 50_000,
    frequency: int = 1,
    country_risk: str = "low",
    recipient_type: str = "known_counterparty",
    time_of_day: str = "day",
    velocity: str = "normal",
    channel: str | None = None,
    has_documents: bool = True,
    details: dict | None = None,
) -> dict:
    card = next(card for card in ACTION_CARDS if card["code"] == card_code)
    return {
        "uid": uuid4().hex,
        "card_code": card_code,
        "amount": amount,
        "frequency": frequency,
        "country_risk": country_risk,
        "recipient_type": recipient_type,
        "time_of_day": time_of_day,
        "velocity": velocity,
        "channel": channel or card["channels"][0],
        "has_documents": has_documents,
        "details": normalize_action_details(
            card_code,
            details if details is not None else default_action_details(card_code),
        ),
    }


initialize_state()
if st.session_state.user is None:
    login_screen()
    st.stop()

home_page = st.Page(render_home, title="Главная", icon=":material/home:", default=True)
scenario_page = st.Page(
    render_scenario,
    title="Сценарий",
    icon=":material/account_tree:",
)
result_page = st.Page(render_result, title="Результат", icon=":material/analytics:")
leaderboard_page = st.Page(
    render_leaderboard,
    title="Лидерборд",
    icon=":material/leaderboard:",
)

with st.sidebar:
    st.markdown(
        """
        <div class="aml-brand">
            <div class="aml-brand-title">AML Simulator</div>
            <div class="aml-brand-caption">Раунд 1 · учебная модель</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="aml-player">
            <div class="aml-player-name">{escape(st.session_state.user['name'])}</div>
            <div class="aml-player-email">{escape(st.session_state.user['email'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="aml-sync">Локальный MVP · без синхронизации</div>',
        unsafe_allow_html=True,
    )
    if st.button(
        "Выйти из профиля",
        icon=":material/logout:",
        width="stretch",
    ):
        st.session_state.user = None
        st.session_state.draft_steps = []
        st.rerun()

navigation = st.navigation(
    {
        "Игра": [home_page, scenario_page],
        "Раунд": [result_page, leaderboard_page],
    },
    position="sidebar",
)
navigation.run()
