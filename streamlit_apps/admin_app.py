from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from backend.app.domain.action_parameters import (
    action_detail_summary,
    context_fields_for,
    context_value_label,
    detail_factor_label,
)
from streamlit_apps.api_client import API_BASE_URL, ApiError, request
from streamlit_apps.demo_admin_data import (
    build_demo_players,
    clear_demo_override,
    clone_rounds,
    demo_board,
    demo_stats,
    update_demo_block,
    update_demo_override,
)
from streamlit_apps.local_store import ACTION_CARDS, resource_snapshot


st.set_page_config(
    page_title="AML Control",
    page_icon=":material/admin_panel_settings:",
    layout="wide",
    initial_sidebar_state="auto",
)
st.markdown(
    """
    <style>
    :root {
        --admin-ink: var(--text-color);
        --admin-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
        --admin-line: color-mix(in srgb, var(--text-color) 18%, transparent);
        --admin-surface: var(--secondary-background-color);
        --admin-soft: color-mix(
            in srgb,
            var(--primary-color) 9%,
            var(--background-color)
        );
        --admin-primary: var(--primary-color);
        --admin-warning: var(--orange-color, #d89022);
    }
    .block-container {
        max-width: 1280px;
        padding-top: 1.35rem;
        padding-bottom: 4rem;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid var(--admin-line);
    }
    [data-testid="stMetric"] {
        min-height: 88px;
        padding: .8rem .9rem;
        border: 1px solid var(--admin-line);
        border-radius: 6px;
        background: var(--admin-surface);
    }
    [data-testid="stMetricLabel"] {color: var(--admin-muted);}
    [data-testid="stMetricValue"] {font-size: 23px;}
    [data-testid="stForm"] {
        padding: 1rem;
        border: 1px solid var(--admin-line);
        border-radius: 6px;
        background: var(--admin-surface);
    }
    h1, h2, h3, p {letter-spacing: 0;}
    .admin-kicker {
        margin-bottom: .35rem;
        color: var(--admin-primary);
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .admin-page-title {
        margin: 0 0 .35rem;
        color: var(--admin-ink);
        font-size: 34px !important;
        line-height: 1.15 !important;
        overflow-wrap: anywhere;
    }
    .admin-subtitle {
        max-width: 820px;
        margin: 0 0 1rem;
        color: var(--admin-muted);
        font-size: 16px;
    }
    .admin-brand {
        padding: .35rem 0 .8rem;
        border-bottom: 1px solid var(--admin-line);
    }
    .admin-brand-title {font-size: 17px; font-weight: 700;}
    .admin-brand-caption {
        margin-top: .2rem;
        color: var(--admin-muted);
        font-size: 12px;
    }
    .admin-session {
        padding: .75rem;
        border: 1px solid var(--admin-line);
        border-radius: 6px;
        background: var(--admin-surface);
    }
    .admin-session strong {display: block; overflow-wrap: anywhere;}
    .admin-session span {color: var(--admin-muted); font-size: 12px;}
    .admin-mode {
        padding: .65rem .75rem;
        border-left: 3px solid var(--admin-warning);
        background: color-mix(
            in srgb,
            var(--admin-warning) 14%,
            var(--background-color)
        );
        color: var(--admin-ink);
        font-size: 13px;
    }
    .admin-lifecycle {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        margin: .8rem 0 1.25rem;
        border-top: 1px solid var(--admin-line);
        border-bottom: 1px solid var(--admin-line);
    }
    .admin-lifecycle-step {
        min-width: 0;
        padding: .7rem .8rem;
        color: var(--admin-muted);
    }
    .admin-lifecycle-step + .admin-lifecycle-step {
        border-left: 1px solid var(--admin-line);
    }
    .admin-lifecycle-step strong {
        display: block;
        color: var(--admin-ink);
        overflow-wrap: anywhere;
    }
    .admin-lifecycle-step[data-state="done"] strong {
        color: var(--admin-primary);
    }
    .admin-lifecycle-step[data-state="current"] {
        background: var(--admin-soft);
    }
    .admin-lifecycle-index {font-size: 11px;}
    .admin-round-meta {
        display: flex;
        flex-wrap: wrap;
        gap: .4rem 1rem;
        margin-bottom: .75rem;
        color: var(--admin-muted);
        font-size: 12px;
    }
    .admin-score-note {
        padding: .7rem .8rem;
        border-left: 3px solid var(--admin-primary);
        background: var(--admin-soft);
        font-size: 13px;
    }
    .admin-player-banner {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: .45rem 1rem;
        padding: .8rem .9rem;
        border: 1px solid var(--admin-line);
        border-left: 4px solid var(--admin-primary);
        border-radius: 6px;
        background: var(--admin-surface);
    }
    .admin-player-banner[data-blocked="true"] {
        border-left-color: var(--red-color, #d65353);
    }
    .admin-player-banner strong {overflow-wrap: anywhere;}
    .admin-player-banner span {color: var(--admin-muted); font-size: 12px;}
    .admin-profile-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: .45rem 1rem;
        margin: .5rem 0 1rem;
    }
    .admin-profile-field {
        min-width: 0;
        padding: .45rem 0;
        border-bottom: 1px solid var(--admin-line);
    }
    .admin-profile-field span {
        display: block;
        color: var(--admin-muted);
        font-size: 11px;
    }
    .admin-profile-field strong {
        display: block;
        margin-top: .1rem;
        overflow-wrap: anywhere;
        font-size: 13px;
    }
    @media (max-width: 760px) {
        .block-container {
            padding-top: 1rem;
            padding-right: .85rem;
            padding-left: .85rem;
        }
        .admin-page-title {font-size: 30px !important;}
        .admin-lifecycle {grid-template-columns: repeat(2, minmax(0, 1fr));}
        .admin-lifecycle-step:nth-child(3) {border-left: 0;}
        .admin-lifecycle-step:nth-child(n+3) {
            border-top: 1px solid var(--admin-line);
        }
        .admin-profile-grid {grid-template-columns: 1fr;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


DEFAULT_GAME_CONFIG = clone_rounds()[0]["game_config"]
STATUS_LABELS = {
    "draft": "Черновик",
    "active": "Активен",
    "scoring": "Скоринг",
    "completed": "Завершен",
}
RISK_LABELS = {
    "normal": "Пропущен",
    "review": "Проверка",
    "suspicious": "Заблокирован",
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
    defaults = {
        "admin_token": None,
        "admin_demo": False,
        "demo_players": None,
        "demo_rounds": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.demo_players is None:
        st.session_state.demo_players = build_demo_players()
    if st.session_state.demo_rounds is None:
        st.session_state.demo_rounds = clone_rounds()


def render_page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="admin-kicker">{escape(kicker)}</div>
        <h1 class="admin-page-title">{escape(title)}</h1>
        <p class="admin-subtitle">{escape(subtitle)}</p>
        """,
        unsafe_allow_html=True,
    )


def render_login() -> None:
    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        render_page_header(
            "AML Control · панель организатора",
            "Управление мастер-классом",
            "Активируйте раунд, следите за отправкой сценариев и запускайте "
            "общий скоринг.",
        )
        with st.form("admin_login"):
            email = st.text_input("Email", value="admin@example.com")
            password = st.text_input("Пароль", type="password")
            submitted = st.form_submit_button(
                "Войти",
                type="primary",
                icon=":material/login:",
                width="stretch",
            )
        if submitted:
            try:
                data = request(
                    "POST",
                    "/auth/login",
                    json={"email": email, "password": password},
                )
                if data["role"] != "admin":
                    st.error("Для входа нужна роль администратора.")
                else:
                    st.session_state.admin_token = data["access_token"]
                    st.rerun()
            except ApiError as exc:
                st.error(str(exc))

        st.divider()
        st.caption("FastAPI пока не запущен? Откройте интерфейс с демонстрационными данными.")
        if st.button(
            "Открыть демо-панель",
            icon=":material/preview:",
            width="stretch",
        ):
            st.session_state.admin_demo = True
            st.rerun()
        st.markdown(
            '<div class="admin-mode">Изменения в демо-панели сохраняются '
            'только в текущей admin-сессии.</div>',
            unsafe_allow_html=True,
        )


def load_rounds() -> list[dict]:
    if st.session_state.admin_demo:
        return st.session_state.demo_rounds
    return request("GET", "/admin/rounds", token=st.session_state.admin_token)


def load_stats(round_id: int) -> dict:
    if st.session_state.admin_demo:
        return demo_stats(st.session_state.demo_players)
    return request(
        "GET",
        f"/admin/rounds/{round_id}/stats",
        token=st.session_state.admin_token,
    )


def load_board(round_id: int) -> list[dict]:
    if st.session_state.admin_demo:
        return demo_board(st.session_state.demo_players)
    return request(
        "GET",
        f"/admin/rounds/{round_id}/board",
        token=st.session_state.admin_token,
    )


def load_players(round_id: int) -> list[dict]:
    if st.session_state.admin_demo:
        return st.session_state.demo_players
    return []


def render_sidebar(rounds: list[dict]) -> dict | None:
    with st.sidebar:
        st.markdown(
            """
            <div class="admin-brand">
                <div class="admin-brand-title">AML Control</div>
                <div class="admin-brand-caption">Панель организатора</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        mode = "Интерактивный прототип" if st.session_state.admin_demo else "Подключено к API"
        endpoint = "Данные admin-сессии" if st.session_state.admin_demo else API_BASE_URL
        st.markdown(
            f"""
            <div class="admin-session">
                <strong>{escape(mode)}</strong>
                <span>{escape(endpoint)}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        selected_round = None
        if rounds:
            round_options = {
                f"#{item['id']} · {item['title']} · "
                f"{STATUS_LABELS.get(item['status'], item['status'])}": item
                for item in rounds
            }
            selected_label = st.selectbox("Текущий раунд", list(round_options))
            selected_round = round_options[selected_label]

        with st.expander("Создать раунд"):
            title = st.text_input("Название", value="Мастер-класс AML")
            if st.button(
                "Создать",
                type="primary",
                icon=":material/add:",
                width="stretch",
                disabled=st.session_state.admin_demo,
            ):
                try:
                    request(
                        "POST",
                        "/admin/rounds",
                        token=st.session_state.admin_token,
                        json={"title": title},
                    )
                    st.rerun()
                except ApiError as exc:
                    st.error(str(exc))
            if st.session_state.admin_demo:
                st.caption("Создание доступно после подключения API.")

        if st.button(
            "Выйти",
            icon=":material/logout:",
            width="stretch",
        ):
            st.session_state.admin_token = None
            st.session_state.admin_demo = False
            st.rerun()
    return selected_round


def render_lifecycle(status: str) -> None:
    statuses = ("draft", "active", "scoring", "completed")
    current_index = statuses.index(status)
    items = []
    for index, value in enumerate(statuses):
        state = "done" if index < current_index else "current" if index == current_index else "todo"
        items.append(
            f'<div class="admin-lifecycle-step" data-state="{state}">'
            f'<span class="admin-lifecycle-index">0{index + 1}</span>'
            f"<strong>{STATUS_LABELS[value]}</strong></div>"
        )
    st.markdown(
        f'<div class="admin-lifecycle">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


def run_round_command(action: str, round_id: int) -> None:
    paths = {
        "activate": f"/admin/rounds/{round_id}/activate",
        "score": f"/admin/rounds/{round_id}/score",
    }
    try:
        result = request(
            "POST",
            paths[action],
            token=st.session_state.admin_token,
        )
        if action == "score":
            st.success(f"Проскорено сценариев: {result['scored_count']}")
        st.rerun()
    except ApiError as exc:
        st.error(str(exc))


def render_command_bar(round_data: dict) -> None:
    status = round_data["status"]
    demo = st.session_state.admin_demo
    activate_col, score_col, refresh_col = st.columns([1.1, 1.5, 0.55])
    if activate_col.button(
        "Активировать",
        icon=":material/play_arrow:",
        width="stretch",
        disabled=demo or status != "draft",
    ):
        run_round_command("activate", round_data["id"])
    if score_col.button(
        "Запустить общий скоринг",
        type="primary",
        icon=":material/model_training:",
        width="stretch",
        disabled=demo or status != "active",
    ):
        run_round_command("score", round_data["id"])
    if refresh_col.button(
        "",
        icon=":material/refresh:",
        help="Обновить данные",
        width="stretch",
    ):
        st.rerun()
    if demo:
        st.caption("Команды раунда показаны как референс и отключены в демо-режиме.")


def render_stats(stats: dict) -> None:
    registered = stats["registered_users"]
    submitted = stats["submitted_scenarios"]
    scored = stats["scored_scenarios"]
    blocked = stats.get("blocked_users", 0)
    participation = submitted / registered if registered else 0
    registered_col, submitted_col, scored_col, blocked_col = st.columns(4)
    registered_col.metric("Зарегистрировано", registered)
    submitted_col.metric("Отправили", submitted)
    scored_col.metric("Оценено", scored)
    blocked_col.metric("Ограничен доступ", blocked)
    st.progress(participation, text="Доля участников с отправленным сценарием")


def factor_display_name(raw_name: str) -> str:
    if raw_name.startswith("card:"):
        code = raw_name.split(":", 1)[1]
        card = next((card for card in ACTION_CARDS if card["code"] == code), None)
        return f"Тип операции: {card['title'] if card else code}"
    if raw_name.startswith("country_risk:"):
        value = raw_name.split(":", 1)[1]
        return f"Риск страны: {context_value_label('country_risk', value)}"
    if raw_name.startswith("recipient:"):
        value = raw_name.split(":", 1)[1]
        return f"Получатель: {context_value_label('recipient_type', value)}"
    if raw_name.startswith("time_of_day:"):
        value = raw_name.split(":", 1)[1]
        return f"Время: {context_value_label('time_of_day', value)}"
    if raw_name.startswith("velocity:"):
        value = raw_name.split(":", 1)[1]
        return f"Темп: {context_value_label('velocity', value)}"
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


def board_rows(board: list[dict]) -> list[dict]:
    rows = []
    for row in board:
        rows.append(
            {
                "Участник": row["participant_name"],
                "Игровой балл": row.get("game_score"),
                "Риск": row["risk_score"],
                "Ресурсы": row.get("resource_score"),
                "Решение": RISK_LABELS.get(row["label"], row["label"]),
                "Доступ": "Заблокирован" if row.get("is_blocked") else "Активен",
                "Источник": "Корректировка" if row.get("is_overridden") else "Модель",
                "Топ-факторы": ", ".join(
                    factor_display_name(item["name"])
                    for item in row.get("top_factors", [])[:2]
                ),
                "Сценарий": row["scenario_id"],
            }
        )
    return rows


def render_board(board: list[dict]) -> None:
    st.subheader("Доска скоринга")
    if not board:
        st.info("Результаты появятся после общего скоринга.")
        return
    decision_col, access_col = st.columns(2)
    labels = ["Все", *RISK_LABELS.values()]
    selected = decision_col.segmented_control(
        "Решение модели", labels, default="Все", selection_mode="single"
    )
    selected_access = access_col.segmented_control(
        "Доступ", ["Все", "Активен", "Заблокирован"], default="Все"
    )
    rows = board_rows(board)
    if selected and selected != "Все":
        rows = [row for row in rows if row["Решение"] == selected]
    if selected_access and selected_access != "Все":
        rows = [row for row in rows if row["Доступ"] == selected_access]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Игровой балл": st.column_config.ProgressColumn(
                "Игровой балл",
                min_value=0,
                max_value=100,
                format="%.1f",
            ),
            "Риск": st.column_config.ProgressColumn(
                "Риск",
                min_value=0,
                max_value=100,
                format="%.1f",
            ),
        },
    )


def render_leaderboard(board: list[dict], players: list[dict]) -> None:
    st.subheader("Рейтинг участников")
    scored = [row for row in board if row.get("game_score") is not None]
    if not scored:
        st.info("Игровой рейтинг появится после скоринга.")
        return
    scored.sort(key=lambda row: row["game_score"], reverse=True)
    rows = [
        {
            "Место": index,
            "Участник": row["participant_name"],
            "Игровой балл": row["game_score"],
            "Риск": row["risk_score"],
            "Ресурсы": row.get("resource_score"),
            "Источник": "Корректировка" if row.get("is_overridden") else "Модель",
        }
        for index, row in enumerate(scored, start=1)
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Игровой балл": st.column_config.ProgressColumn(
                "Игровой балл", min_value=0, max_value=100, format="%.1f"
            ),
            "Риск": st.column_config.ProgressColumn(
                "Риск", min_value=0, max_value=100, format="%.1f"
            ),
            "Ресурсы": st.column_config.ProgressColumn(
                "Ресурсы", min_value=0, max_value=100, format="%.1f"
            ),
        },
    )
    st.caption(
        "Рейтинг сортируется по игровому баллу. Ручная корректировка помечается "
        "отдельным источником и не изменяет исходный результат модели."
    )
    render_leaderboard_editor(players)


def render_leaderboard_editor(players: list[dict]) -> None:
    st.divider()
    st.subheader("Ручная корректировка")
    if not st.session_state.admin_demo:
        st.info(
            "Элементы управления подготовлены. Для рабочего режима потребуется "
            "admin API корректировок и журнал аудита.",
            icon=":material/database:",
        )
        return

    scored_players = [
        player
        for player in players
        if (player.get("scenario") or {}).get("result")
    ]
    if not scored_players:
        st.info("Нет оцененных участников для корректировки.")
        return

    player_by_id = {player["id"]: player for player in scored_players}
    options = list(player_by_id)
    preferred = st.session_state.get("leaderboard_player_select")
    selected_index = options.index(preferred) if preferred in options else 0
    player_id = st.selectbox(
        "Участник",
        options,
        index=selected_index,
        format_func=lambda value: (
            f"{player_by_id[value]['name']} · {player_by_id[value]['email']}"
        ),
        key="leaderboard_player_select",
    )
    player = player_by_id[player_id]
    result = player["scenario"]["result"]
    override = player.get("leaderboard_override") or {}

    st.caption(
        f"Расчет модели: игровой балл {result['game_score']:.1f}, "
        f"риск {result['risk_score']:.1f}, ресурсы {result['resource_score']:.1f}."
    )
    with st.form(f"leaderboard_override_{player_id}"):
        game_col, risk_col, resource_col = st.columns(3)
        game_score = game_col.number_input(
            "Игровой балл",
            min_value=0.0,
            max_value=100.0,
            value=float(override.get("game_score", result["game_score"])),
            step=0.1,
        )
        risk_score = risk_col.number_input(
            "Риск модели",
            min_value=0.0,
            max_value=100.0,
            value=float(override.get("risk_score", result["risk_score"])),
            step=0.1,
        )
        resource_score = resource_col.number_input(
            "Оценка ресурсов",
            min_value=0.0,
            max_value=100.0,
            value=float(override.get("resource_score", result["resource_score"])),
            step=0.1,
        )
        reason = st.text_input(
            "Основание корректировки",
            value=override.get("reason", ""),
            placeholder="Например, решение апелляционной комиссии",
        )
        submitted = st.form_submit_button(
            "Сохранить корректировку",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )
    if submitted:
        if len(reason.strip()) < 3:
            st.error("Укажите основание корректировки.")
        else:
            update_demo_override(
                players,
                player_id,
                game_score=game_score,
                risk_score=risk_score,
                resource_score=resource_score,
                reason=reason,
            )
            st.toast("Корректировка сохранена", icon=":material/check:")
            st.rerun()

    if override and st.button(
        "Вернуть расчет модели",
        icon=":material/undo:",
        key=f"clear_override_{player_id}",
    ):
        clear_demo_override(players, player_id)
        st.rerun()


def format_money(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def format_datetime(value: str | None) -> str:
    if not value:
        return "—"
    return value.replace("T", " ")[:16]


def render_profile_grid(items: list[tuple[str, str]]) -> None:
    fields = "".join(
        '<div class="admin-profile-field">'
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in items
    )
    st.markdown(
        f'<div class="admin-profile-grid">{fields}</div>',
        unsafe_allow_html=True,
    )


def render_access_control(player: dict) -> None:
    with st.expander("Управление доступом"):
        if not st.session_state.admin_demo:
            st.info("Блокировка будет подключена к admin API.")
            return
        if player["is_blocked"]:
            st.warning(
                f"Доступ заблокирован. Причина: "
                f"{player.get('blocked_reason') or 'не указана'}."
            )
            if st.button(
                "Разблокировать игрока",
                icon=":material/lock_open:",
                key=f"unblock_{player['id']}",
            ):
                update_demo_block(
                    st.session_state.demo_players,
                    player["id"],
                    False,
                )
                st.toast("Доступ восстановлен", icon=":material/check:")
                st.rerun()
            return

        reason = st.text_input(
            "Причина блокировки",
            placeholder="Краткое основание решения",
            key=f"block_reason_{player['id']}",
        )
        confirmed = st.checkbox(
            "Подтверждаю ограничение доступа",
            key=f"block_confirm_{player['id']}",
        )
        if st.button(
            "Заблокировать игрока",
            icon=":material/block:",
            key=f"block_{player['id']}",
            disabled=not confirmed,
        ):
            if len(reason.strip()) < 3:
                st.error("Укажите причину блокировки.")
            else:
                update_demo_block(
                    st.session_state.demo_players,
                    player["id"],
                    True,
                    reason,
                )
                st.toast("Доступ ограничен", icon=":material/block:")
                st.rerun()


def render_player_chain(player: dict) -> None:
    scenario = player.get("scenario")
    if scenario is None:
        st.info("Участник не отправил сценарий.", icon=":material/hourglass_empty:")
        return

    steps = scenario["steps"]
    resources = scenario.get("result", {}).get("resources") or resource_snapshot(steps)
    card_lookup = {card["code"]: card for card in ACTION_CARDS}
    chain_rows = []
    parameter_rows = []
    for index, step in enumerate(steps, start=1):
        card = card_lookup[step["card_code"]]
        impact = resources["steps"][index - 1]
        chain_rows.append(
            {
                "Шаг": index,
                "Действие": card["title"],
                "Сумма": format_money(step["amount"]),
                "Повторы": step["frequency"],
                "Канал": CHANNEL_LABELS.get(step.get("channel", ""), "—"),
                "Баланс после": format_money(impact["balance_after"]),
                "Энергия": impact["energy_after"],
                "Время": impact["time_after"],
                "Доверие": impact["trust_after"],
            }
        )
        parameter_rows.extend(
            [
                {
                    "Шаг": index,
                    "Группа": "Операция",
                    "Параметр": "Сумма",
                    "Значение": format_money(step["amount"]),
                },
                {
                    "Шаг": index,
                    "Группа": "Операция",
                    "Параметр": "Повторы",
                    "Значение": str(step["frequency"]),
                },
                {
                    "Шаг": index,
                    "Группа": "Операция",
                    "Параметр": "Канал",
                    "Значение": CHANNEL_LABELS.get(step.get("channel", ""), "—"),
                },
            ]
        )
        for field in context_fields_for(step["card_code"]):
            value = step.get(field["key"], field["default"])
            parameter_rows.append(
                {
                    "Шаг": index,
                    "Группа": "Контекст",
                    "Параметр": field["label"],
                    "Значение": context_value_label(field["key"], value),
                }
            )
        for item in action_detail_summary(step["card_code"], step.get("details")):
            parameter_rows.append(
                {
                    "Шаг": index,
                    "Группа": "Тип действия",
                    "Параметр": item["label"],
                    "Значение": item["value"],
                }
            )

    st.dataframe(
        pd.DataFrame(chain_rows),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Итог: проведено {format_money(resources['outflow'])}, "
        f"комиссии {format_money(resources['fees'])}, "
        f"эффективность ресурсов {resources['resource_score']:.1f}."
    )
    with st.expander("Все параметры шагов"):
        st.dataframe(
            pd.DataFrame(parameter_rows),
            hide_index=True,
            width="stretch",
        )


def render_player_factors(player: dict) -> None:
    result = player.get("scenario", {}).get("result") if player.get("scenario") else None
    if result is None:
        st.info("Факторы появятся после скоринга сценария.")
        return
    factors = result["explanation"]["all_factors"]
    rows = [
        {
            "Шаг": factor["step"] or "Цепочка",
            "Фактор": factor_display_name(factor["name"]),
            "Вклад": factor["points"],
            "Объяснение": factor.get("description", ""),
        }
        for factor in factors
    ]
    chart_rows = sorted(rows, key=lambda item: abs(item["Вклад"]), reverse=True)[:8]
    if chart_rows:
        st.bar_chart(
            pd.DataFrame(chart_rows),
            x="Фактор",
            y="Вклад",
            horizontal=True,
            width="stretch",
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(result["explanation"]["note"])


def render_player_activity(player: dict) -> None:
    rows = [
        {
            "Время": item["time"],
            "Событие": item["event"],
            "Источник": item["source"],
        }
        for item in reversed(player.get("activity", []))
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    override = player.get("leaderboard_override")
    if override:
        st.info(
            f"Последняя корректировка: {format_datetime(override['updated_at'])}. "
            f"Основание: {override['reason']}."
        )


def render_players(players: list[dict]) -> None:
    st.subheader("Участники раунда")
    if not players:
        st.info(
            "Карточка игрока подготовлена для целевого API. В текущем backend еще нет "
            "контракта списка участников и управления доступом.",
            icon=":material/api:",
        )
        return

    search_col, status_col = st.columns([1.5, 1])
    search = search_col.text_input(
        "Поиск",
        placeholder="Имя, email, школа или команда",
        icon=":material/search:",
    ).strip().lower()
    status_filter = status_col.selectbox(
        "Статус",
        ["Все", "Активные", "Заблокированные", "Без сценария"],
    )

    filtered = []
    for player in players:
        haystack = " ".join(
            str(player.get(key, ""))
            for key in ("name", "email", "organization", "team")
        ).lower()
        if search and search not in haystack:
            continue
        if status_filter == "Активные" and player["is_blocked"]:
            continue
        if status_filter == "Заблокированные" and not player["is_blocked"]:
            continue
        if status_filter == "Без сценария" and player.get("scenario") is not None:
            continue
        filtered.append(player)

    if not filtered:
        st.info("По выбранным условиям участники не найдены.")
        return

    overview_rows = [
        {
            "Игрок": player["name"],
            "Email": player["email"],
            "Команда": player["team"],
            "Доступ": "Заблокирован" if player["is_blocked"] else "Активен",
            "Сценарий": "Оценен" if player.get("scenario") else "Нет",
            "Последняя активность": format_datetime(player["last_seen_at"]),
        }
        for player in filtered
    ]
    st.dataframe(pd.DataFrame(overview_rows), hide_index=True, width="stretch")

    player_by_id = {player["id"]: player for player in filtered}
    options = list(player_by_id)
    preferred = st.session_state.get("player_profile_select")
    selected_index = options.index(preferred) if preferred in options else 0
    player_id = st.selectbox(
        "Открыть карточку игрока",
        options,
        index=selected_index,
        format_func=lambda value: (
            f"{player_by_id[value]['name']} · {player_by_id[value]['email']}"
        ),
        key="player_profile_select",
    )
    player = player_by_id[player_id]
    scenario = player.get("scenario")
    board = demo_board(players) if st.session_state.admin_demo else []
    board_row = next(
        (row for row in board if row["participant_id"] == player_id),
        None,
    )
    rank = next(
        (index for index, row in enumerate(board, start=1) if row["participant_id"] == player_id),
        None,
    )

    st.markdown(
        '<div class="admin-player-banner" '
        f'data-blocked="{str(player["is_blocked"]).lower()}">'
        f"<div><strong>{escape(player['name'])}</strong>"
        f"<span>{escape(player['email'])}</span></div>"
        f"<strong>{'Доступ заблокирован' if player['is_blocked'] else 'Доступ активен'}</strong>"
        "</div>",
        unsafe_allow_html=True,
    )

    rank_col, score_col, attempts_col, steps_col = st.columns(4)
    rank_col.metric("Место", rank if rank is not None else "—")
    score_col.metric(
        "Игровой балл",
        f"{board_row['game_score']:.1f}" if board_row else "—",
    )
    attempts_col.metric("Попытки", scenario.get("attempts", 0) if scenario else 0)
    steps_col.metric("Шаги", len(scenario.get("steps", [])) if scenario else 0)

    profile_col, round_col = st.columns(2, gap="large")
    with profile_col:
        st.markdown("**Профиль**")
        render_profile_grid(
            [
                ("ID игрока", player["id"]),
                ("Email", player["email"]),
                ("Организация", player["organization"]),
                ("Команда", player["team"]),
                ("Регистрация", format_datetime(player["registered_at"])),
                ("Последняя активность", format_datetime(player["last_seen_at"])),
                ("Количество входов", str(player["login_count"])),
                ("Статус доступа", "Заблокирован" if player["is_blocked"] else "Активен"),
            ]
        )
    with round_col:
        st.markdown("**Участие в раунде**")
        render_profile_grid(
            [
                ("ID сценария", scenario["id"] if scenario else "—"),
                ("Статус сценария", "Оценен" if scenario else "Не отправлен"),
                ("Отправлен", format_datetime(scenario.get("submitted_at") if scenario else None)),
                ("Решение", RISK_LABELS.get(board_row["label"], "—") if board_row else "—"),
                ("Риск модели", f"{board_row['risk_score']:.1f}" if board_row else "—"),
                ("Ресурсы", f"{board_row['resource_score']:.1f}" if board_row else "—"),
                (
                    "Источник результата",
                    "Корректировка" if board_row and board_row["is_overridden"] else "Модель",
                ),
                ("Причина блокировки", player.get("blocked_reason") or "—"),
            ]
        )

    render_access_control(player)
    chain_tab, factors_tab, activity_tab = st.tabs(
        ["Цепочка действий", "Факторы модели", "История"]
    )
    with chain_tab:
        render_player_chain(player)
    with factors_tab:
        render_player_factors(player)
    with activity_tab:
        render_player_activity(player)


def render_settings(round_data: dict) -> None:
    st.subheader("Конфигурация игры")
    st.caption(
        "После активации конфигурация фиксируется. Редактирование будет подключено "
        "вместе с соответствующим API-контрактом."
    )
    config = {**DEFAULT_GAME_CONFIG, **round_data.get("game_config", {})}
    balance_col, target_col = st.columns(2)
    balance_col.number_input(
        "Стартовый баланс, ₽",
        value=int(config["initial_balance"]),
        disabled=True,
    )
    target_col.number_input(
        "Цель оборота, ₽",
        value=int(config["target_outflow"]),
        disabled=True,
    )
    energy_col, time_col, trust_col, actions_col = st.columns(4)
    energy_col.number_input(
        "Энергия",
        value=int(config["initial_energy"]),
        disabled=True,
    )
    time_col.number_input(
        "Время",
        value=int(config["initial_time"]),
        disabled=True,
    )
    trust_col.number_input(
        "Доверие",
        value=int(config["initial_trust"]),
        disabled=True,
    )
    actions_col.number_input(
        "Лимит действий",
        value=int(config["max_actions"]),
        disabled=True,
    )
    st.text_input(
        "Версия скоринга",
        value=str(config["scoring_version"]),
        disabled=True,
    )
    st.button(
        "Сохранить конфигурацию",
        type="primary",
        icon=":material/save:",
        disabled=True,
    )


def render_admin() -> None:
    try:
        rounds = load_rounds()
    except ApiError as exc:
        render_page_header(
            "AML Control",
            "API недоступен",
            "Проверьте FastAPI или откройте демо-предпросмотр интерфейса.",
        )
        st.error(str(exc))
        if st.button("Открыть демо-панель", icon=":material/preview:"):
            st.session_state.admin_demo = True
            st.rerun()
        return

    selected_round = render_sidebar(rounds)
    if selected_round is None:
        render_page_header(
            "AML Control",
            "Раундов пока нет",
            "Создайте первый раунд в боковой панели.",
        )
        st.info("После создания здесь появится мониторинг мероприятия.")
        return

    render_page_header(
        f"Раунд #{selected_round['id']} · "
        f"{STATUS_LABELS.get(selected_round['status'], selected_round['status'])}",
        selected_round["title"],
        "Контролируйте готовность аудитории, проверяйте цепочки игроков и "
        "управляйте результатами раунда.",
    )
    st.markdown(
        '<div class="admin-round-meta">'
        f"<span>Источник: {'демо-данные' if st.session_state.admin_demo else 'FastAPI'}</span>"
        f"<span>Версия скоринга: "
        f"{escape(str(selected_round.get('game_config', {}).get('scoring_version', '—')))}</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    render_lifecycle(selected_round["status"])
    render_command_bar(selected_round)
    st.divider()

    try:
        stats = load_stats(selected_round["id"])
        board = load_board(selected_round["id"])
        players = load_players(selected_round["id"])
    except ApiError as exc:
        st.error(str(exc))
        return

    monitoring_tab, players_tab, leaderboard_tab, settings_tab = st.tabs(
        ["Мониторинг", "Игроки", "Лидерборд", "Настройки раунда"]
    )
    with monitoring_tab:
        render_stats(stats)
        st.markdown(
            '<div class="admin-score-note">Перед скорингом убедитесь, что число '
            "отправленных сценариев соответствует ожидаемой аудитории.</div>",
            unsafe_allow_html=True,
        )
        render_board(board)
    with players_tab:
        render_players(players)
    with leaderboard_tab:
        render_leaderboard(board, players)
    with settings_tab:
        render_settings(selected_round)


initialize_state()
if st.session_state.admin_token is None and not st.session_state.admin_demo:
    render_login()
    st.stop()

render_admin()
