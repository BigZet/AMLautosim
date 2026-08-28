from __future__ import annotations

import sys
from html import escape
from pathlib import Path
from typing import Any

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

st.set_page_config(
    page_title="AML Control Panel",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --admin-ink: var(--text-color);
        --admin-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
        --admin-line: color-mix(in srgb, var(--text-color) 18%, transparent);
        --admin-surface: var(--secondary-background-color);
        --admin-soft: color-mix(in srgb, var(--primary-color) 9%, var(--background-color));
        --admin-primary: var(--primary-color);
        --admin-warning: #d89022;
        --admin-success: #2e9e5b;
        --admin-danger: #d65353;
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
    .admin-kicker {
        margin-bottom: .35rem;
        color: var(--admin-primary);
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .admin-page-title {
        margin: 0 0 .35rem;
        font-size: 32px !important;
        font-weight: 800;
        line-height: 1.15 !important;
    }
    .admin-subtitle {
        max-width: 820px;
        margin: 0 0 1rem;
        color: var(--admin-muted);
        font-size: 15px;
    }
    .admin-lifecycle {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        margin: .8rem 0 1.25rem;
        border: 1px solid var(--admin-line);
        border-radius: 6px;
        overflow: hidden;
    }
    .admin-lifecycle-step {
        padding: .7rem .8rem;
        background: var(--admin-surface);
        color: var(--admin-muted);
        font-size: 13px;
        border-right: 1px solid var(--admin-line);
    }
    .admin-lifecycle-step:last-child {
        border-right: none;
    }
    .admin-lifecycle-step[data-state="current"] {
        background: var(--admin-soft);
        color: var(--admin-primary);
        font-weight: 700;
    }
    .admin-brand {
        padding: .35rem 0 .8rem;
        border-bottom: 1px solid var(--admin-line);
    }
    .admin-brand-title {font-size: 17px; font-weight: 700;}
    .admin-brand-caption {margin-top: .2rem; color: var(--admin-muted); font-size: 12px;}
    .admin-session {
        padding: .75rem;
        border: 1px solid var(--admin-line);
        border-radius: 6px;
        background: var(--admin-surface);
        margin: .5rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_api_client() -> SimulatorAPIClient:
    return SimulatorAPIClient()


def init_admin_state() -> None:
    if "admin_session_id" not in st.session_state:
        st.session_state.admin_session_id = None
    if "admin_user" not in st.session_state:
        st.session_state.admin_user = None


def format_money(val: float | int) -> str:
    return f"{val:,.0f} ₽".replace(",", " ")


def render_admin_login(client: SimulatorAPIClient) -> None:
    st.markdown('<div class="admin-kicker">Панель управления мастер-классом</div>', unsafe_allow_html=True)
    st.markdown('<div class="admin-page-title">⚙️ AML Control</div>', unsafe_allow_html=True)
    st.markdown('<div class="admin-subtitle">Авторизация организатора и ведущего мастер-класса</div>', unsafe_allow_html=True)

    with st.form("admin_login_form"):
        email = st.text_input("Email администратора", value="admin@aml.local")
        password = st.text_input("Пароль", type="password", value="admin12345")
        submit = st.form_submit_button("Войти в панель управления", use_container_width=True, type="primary")

        if submit:
            try:
                res = client.login(email.strip(), password, audience="admin")
                st.session_state.admin_session_id = res["session_id"]
                st.session_state.admin_user = res["user"]
                st.success("Успешный вход в панель администратора!")
                st.rerun()
            except APIClientError as e:
                st.error(f"Ошибка входа: {e.message}")


def render_lifecycle(status: str) -> None:
    steps = [
        ("1. Черновик", status == "draft"),
        ("2. Активен (Сбор)", status == "active"),
        ("3. Скоринг", False),
        ("4. Завершен (Итоги)", status == "completed"),
    ]
    html = '<div class="admin-lifecycle">'
    for label, is_current in steps:
        state_attr = 'data-state="current"' if is_current else ""
        html += f'<div class="admin-lifecycle-step" {state_attr}>{escape(label)}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_monitoring_tab(client: SimulatorAPIClient, round_id: int, round_data: dict[str, Any], session_id: str) -> None:
    st.subheader("📊 Мониторинг готовности аудитории")

    try:
        stats = client.admin_get_stats(round_id, session_id)
    except Exception as e:
        st.error(f"Ошибка получения статистики: {e}")
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Зарегистрировано", stats["registered_users"])
    with c2:
        st.metric("Активные участники", stats["active_users"])
    with c3:
        st.metric("Сценарии в черновике", stats["draft_scenarios"])
    with c4:
        st.metric("Отправлено на скоринг", stats["submitted_scenarios"], delta=f"{stats['submitted_scenarios']} готово")

    st.markdown("---")
    st.subheader("⚡ Управление раундом")

    status = round_data["status"]
    if status == "draft":
        st.info("Раунд находится в режиме черновика. Участники ждут старта.")
        if st.button("🚀 Активировать раунд для участников", type="primary", use_container_width=True):
            try:
                client.admin_activate_round(round_id, session_id)
                st.success("Раунд активирован!")
                st.rerun()
            except APIClientError as e:
                st.error(f"Ошибка активации: {e.message}")

    elif status == "active":
        st.info("Раунд **АКТИВЕН**. Участники заполняют сценарии. После завершения времени запустите пакетный скоринг.")
        c_act1, c_act2 = st.columns([0.7, 0.3])
        with c_act1:
            st.write(f"Готово к скорингу: **{stats['submitted_scenarios']}** сценариев. Не отправлено: **{stats['draft_scenarios']}**.")
        with c_act2:
            if st.button("🏁 Запустить скоринг всех сценариев", type="primary", use_container_width=True):
                try:
                    res = client.admin_trigger_scoring(round_id, session_id)
                    st.balloons()
                    st.success(f"Скоринг успешно завершен! Оценено {res['scored_count']} сценариев за {res['duration_ms']} мс.")
                    st.rerun()
                except APIClientError as e:
                    st.error(f"Ошибка запуска скоринга: {e.message}")

    elif status == "completed":
        st.success("Раунд **ЗАВЕРШЕН**. Результаты опубликованы.")
        summary = round_data.get("scoring_summary") or {}
        if summary:
            st.json(summary)

    st.markdown("---")
    st.subheader("🏆 Текущий лидерборд раунда")
    try:
        lb_data = client.get_leaderboard(round_id, session_id)
        rows = lb_data.get("rows", [])
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.caption("Лидерборд будет сформирован после запуска скоринга.")
    except Exception as e:
        st.error(f"Ошибка загрузки лидерборда: {e}")


def render_players_tab(client: SimulatorAPIClient, round_id: int, session_id: str) -> None:
    st.subheader("👥 Участники и инспекция цепочек")

    c_f1, c_f2, c_f3 = st.columns([0.5, 0.25, 0.25])
    with c_f1:
        search_query = st.text_input("🔍 Поиск по имени или email", value="")
    with c_f2:
        access_filter = st.selectbox("Доступ", ["all", "active", "blocked"])
    with c_f3:
        status_filter = st.selectbox("Статус сценария", ["all", "submitted", "scored", "draft", "none"])

    try:
        players = client.admin_list_participants(round_id, search_query, access_filter, status_filter, session_id)
    except Exception as e:
        st.error(f"Ошибка загрузки участников: {e}")
        return

    if not players:
        st.info("Участники не найдены.")
        return

    df_players = pd.DataFrame(players)
    st.dataframe(
        df_players[["id", "display_name", "email", "scenario_status", "game_score", "is_blocked"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("🔍 Детальный анализ цепочки игрока")

    player_options = {f"#{p['id']} {p['display_name']} ({p['email']})": p["id"] for p in players}
    chosen_label = st.selectbox("Выберите участника", list(player_options.keys()))
    participant_id = player_options[chosen_label]

    try:
        detail = client.admin_get_participant_detail(round_id, participant_id, session_id)
    except Exception as e:
        st.error(f"Ошибка загрузки деталей: {e}")
        return

    p_user = detail["user"]
    p_scen = detail.get("scenario")
    p_res = detail.get("result")

    c_u1, c_u2 = st.columns([0.7, 0.3])
    with c_u1:
        st.markdown(f"**Email:** `{p_user['email']}` | **Display Name:** `{p_user['display_name']}`")
        status_badge = "🔴 Заблокирован" if p_user["is_blocked"] else "🟢 Активен"
        st.markdown(f"**Статус аккаунта:** {status_badge}")
    with c_u2:
        if not p_user["is_blocked"]:
            reason_block = st.text_input("Причина блокировки", value="Нарушение правил мастер-класса", key=f"blk_rsn_{participant_id}")
            if st.button("🚫 Заблокировать участника", key=f"btn_blk_{participant_id}", use_container_width=True):
                try:
                    client.admin_update_access(round_id, participant_id, blocked=True, reason=reason_block, expected_access_revision=p_user["access_revision"], session_id=session_id)
                    st.success("Участник заблокирован!")
                    st.rerun()
                except APIClientError as e:
                    st.error(f"Ошибка блокировки: {e.message}")
        else:
            if st.button("✅ Разблокировать участника", key=f"btn_unblk_{participant_id}", use_container_width=True):
                try:
                    client.admin_update_access(round_id, participant_id, blocked=False, reason="Разблокирован организатором", expected_access_revision=p_user["access_revision"], session_id=session_id)
                    st.success("Участник разблокирован!")
                    st.rerun()
                except APIClientError as e:
                    st.error(f"Ошибка разблокировки: {e.message}")

    if p_scen and p_scen.get("steps"):
        st.markdown(f"#### Цепочка операций ({len(p_scen['steps'])} действий)")
        for idx, s in enumerate(p_scen["steps"]):
            with st.container(border=True):
                st.markdown(f"**Шаг {idx+1}: {s.get('card_code')}** — `{format_money(s.get('amount', 0))}` × `{s.get('frequency', 1)}`")
                st.caption(f"Контекст: {s.get('context')} | Детали: {s.get('action_details') or s.get('details')}")

        if p_res and p_res.get("explanation"):
            exp = p_res["explanation"]
            catboost_feats = exp.get("catboost_features_payload")
            if catboost_feats:
                st.markdown("---")
                render_catboost_features_inspector(catboost_feats)
    else:
        st.info("Участник еще не сформировал сценарий.")


def render_leaderboard_tab(client: SimulatorAPIClient, round_id: int, session_id: str) -> None:
    st.subheader("🏆 Лидерборд и ручные корректировки")

    try:
        lb_data = client.get_leaderboard(round_id, session_id)
        rows = lb_data.get("rows", [])
    except Exception as e:
        st.error(f"Ошибка загрузки лидерборда: {e}")
        return

    if not rows:
        st.info("Лидерборд пока пуст. Запустите скоринг на вкладке «Мониторинг».")
        return

    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("✏️ Ручная корректировка баллов участника")

    player_options = {f"#{r['rank']} {r['display_name']} (Итоговый: {r['game_score']})": r for r in rows}
    chosen_label = st.selectbox("Выберите участника для корректировки", list(player_options.keys()))
    chosen_player = player_options[chosen_label]
    p_user_id = chosen_player["user_id"]

    with st.form("adj_form"):
        st.write(f"Участник: **{chosen_player['display_name']}** (Текущий балл: {chosen_player['game_score']})")
        new_score = st.number_input("Новый итоговый балл (Game Score Override)", min_value=0.0, max_value=100.0, value=float(chosen_player["game_score"]), step=1.0)
        adj_reason = st.text_input("Обоснование ручной корректировки (обязательно)", value="Бонус за демонстрацию кейса")
        submit_adj = st.form_submit_button("Применить корректировку", type="primary", use_container_width=True)

        if submit_adj:
            if not adj_reason.strip():
                st.error("Укажите причину корректировки!")
            else:
                try:
                    client.admin_update_leaderboard_adjustment(
                        round_id,
                        p_user_id,
                        expected_revision=chosen_player.get("adjustment_revision", 0),
                        reason=adj_reason.strip(),
                        game_score_override=str(new_score),
                        session_id=session_id,
                    )
                    st.success("Корректировка успешно сохранена!")
                    st.rerun()
                except APIClientError as e:
                    st.error(f"Ошибка сохранения: {e.message}")


def render_settings_tab(client: SimulatorAPIClient, round_id: int, round_data: dict[str, Any], session_id: str) -> None:
    st.subheader("⚙️ Конфигурация раунда и журнал аудита")

    g_cfg = round_data.get("game_config", {})
    res_cfg = g_cfg.get("resources", {})
    obj_cfg = g_cfg.get("objectives", {})

    st.markdown("##### Параметры игры")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.text_input("Стартовый баланс", value=str(res_cfg.get("initial_balance", "250000.00")), disabled=True)
    with c2:
        st.text_input("Стартовая энергия", value=str(res_cfg.get("initial_energy", 14)), disabled=True)
    with c3:
        st.text_input("Стартовое время", value=str(res_cfg.get("initial_time", 18)), disabled=True)
    with c4:
        st.text_input("Цель оборота", value=str(obj_cfg.get("target_outflow", "150000.00")), disabled=True)

    st.markdown("---")
    st.subheader("📜 Журнал аудита действий (Audit Trail)")
    try:
        audit_data = client.admin_get_audit_events(round_id, session_id)
        events = audit_data.get("rows", [])
        if events:
            st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)
        else:
            st.caption("События аудита отсутствуют.")
    except Exception as e:
        st.error(f"Ошибка загрузки аудита: {e}")


def main() -> None:
    init_admin_state()
    client = get_api_client()

    if not st.session_state.admin_session_id or not st.session_state.admin_user:
        render_admin_login(client)
        return

    admin_user = st.session_state.admin_user
    session_id = st.session_state.admin_session_id

    with st.sidebar:
        st.markdown(
            """
            <div class="admin-brand">
                <div class="admin-brand-title">⚙️ AML Control Panel</div>
                <div class="admin-brand-caption">Организатор мастер-класса</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="admin-session">
                <strong>👤 {escape(admin_user.get('display_name', 'Организатор'))}</strong>
                <span>{escape(admin_user.get('email', ''))}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Выйти из панели", icon=":material/logout:", use_container_width=True):
            try:
                client.logout(session_id)
            except Exception:
                pass
            st.session_state.admin_session_id = None
            st.session_state.admin_user = None
            st.rerun()

    # Load rounds
    try:
        rounds_list = client.admin_list_rounds(session_id)
    except Exception as e:
        st.error(f"Ошибка загрузки раундов: {e}")
        return

    if not rounds_list:
        st.warning("В системе нет созданных раундов.")
        return

    round_options = {f"#{r['id']} {r['title']} · {r['status'].upper()}": r for r in rounds_list}
    selected_label = st.selectbox("Текущий раунд мастер-класса", list(round_options.keys()))
    selected_round = round_options[selected_label]
    round_id = selected_round["id"]

    st.markdown(f'<div class="admin-kicker">Раунд #{round_id} · {selected_round["status"].upper()}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="admin-page-title">{escape(selected_round["title"])}</div>', unsafe_allow_html=True)
    st.markdown('<div class="admin-subtitle">Контролируйте готовность аудитории, проверяйте цепочки игроков и управляйте результатами раунда.</div>', unsafe_allow_html=True)

    render_lifecycle(selected_round["status"])
    st.markdown("---")

    monitoring_tab, players_tab, leaderboard_tab, settings_tab = st.tabs(
        ["📊 Мониторинг", "👥 Игроки", "🏆 Лидерборд", "⚙️ Настройки раунда"]
    )

    with monitoring_tab:
        render_monitoring_tab(client, round_id, selected_round, session_id)
    with players_tab:
        render_players_tab(client, round_id, session_id)
    with leaderboard_tab:
        render_leaderboard_tab(client, round_id, session_id)
    with settings_tab:
        render_settings_tab(client, round_id, selected_round, session_id)


if __name__ == "__main__":
    main()
