"""Administrator Streamlit application.

Reads and writes exclusively through `/api/v1/admin/*`. There is no demo state
and no local store: every number on screen comes from PostgreSQL through
FastAPI.
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
    ADMIN_COOKIE,
    clear_session,
    get_api_client,
    get_cookie_controller,
    reset_user_state,
    resolve_session,
    store_session,
)

st.set_page_config(
    page_title="AML Workshop Control",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

STYLES = """
<style>
:root { --aml-line: color-mix(in srgb, var(--text-color) 18%, transparent);
        --aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent); }
.block-container { max-width: 1400px; padding-top: 1.2rem; }
.aml-kicker { font-size: 12px; font-weight: 700; text-transform: uppercase;
    color: var(--primary-color); }
.aml-title { font-size: 28px; font-weight: 800; margin: .2rem 0 .3rem; }
.aml-subtitle { color: var(--aml-muted); margin-bottom: 1rem; }
table.aml-table { width: 100%; border-collapse: collapse; font-size: 14px; }
table.aml-table th, table.aml-table td {
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
    "none": "Нет сценария",
}


def header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(f'<div class="aml-kicker">{escape(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="aml-title">{escape(title)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="aml-subtitle">{escape(subtitle)}</div>', unsafe_allow_html=True)


def marker(testid: str, value: Any) -> None:
    st.markdown(
        f'<span data-testid="{escape(testid)}" style="display:none">{escape(str(value))}</span>',
        unsafe_allow_html=True,
    )


def show_flash() -> None:
    flash = st.session_state.get("flash")
    if not flash:
        return
    kind, message = flash
    {"success": st.success, "error": st.error, "warning": st.warning}.get(kind, st.info)(
        message
    )
    marker(f"flash-{kind}", message)
    st.session_state["flash"] = None


def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def login_screen(client: Any, controller: Any) -> None:
    header("AML Workshop Control", "Вход администратора", "Управление раундом и скорингом.")
    marker("auth-state", "anonymous")
    show_flash()
    with st.form("admin_login"):
        email = st.text_input("Email", key="admin_email")
        password = st.text_input("Пароль", type="password", key="admin_password")
        submitted = st.form_submit_button("Войти", type="primary", use_container_width=True)
    if submitted:
        try:
            created = client.login(email.strip(), password, audience="admin")
        except APIClientError as error:
            set_flash("error", error.message)
            st.rerun()
            return
        st.session_state["session_id"] = created["session_id"]
        st.session_state["user"] = created["user"]
        store_session(
            controller, ADMIN_COOKIE, created["session_id"], created.get("expires_at")
        )
        st.rerun()


def select_round(client: Any, session_id: str) -> dict[str, Any] | None:
    rounds = client.admin_list_rounds(session_id)
    if not rounds:
        st.warning("Раундов пока нет.")
        return None
    options = {f"#{item['id']} · {item['title']} ({item['status']})": item for item in rounds}
    chosen = st.selectbox("Раунд", list(options), key="admin_round_select")
    return options[chosen]


def page_monitoring() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header("Мониторинг", "Состояние раунда", "Счётчики читаются напрямую из PostgreSQL.")
    show_flash()

    round_obj = select_round(client, session_id)
    if not round_obj:
        return
    round_id = round_obj["id"]
    marker("round-id", round_id)
    marker("round-status", round_obj["status"])

    stats = client.admin_get_stats(round_id, session_id)
    columns = st.columns(6)
    tiles = (
        ("Участники", stats["registered_users"], "registered"),
        ("Заблокировано", stats["blocked_users"], "blocked"),
        ("Черновики", stats["draft_scenarios"], "drafts"),
        ("Отправлено", stats["submitted_scenarios"], "submitted"),
        ("Оценено", stats["scored_scenarios"], "scored"),
        ("В лидерборде", stats["public_leaderboard_rows"], "board"),
    )
    for column, (label, value, testid) in zip(columns, tiles, strict=False):
        with column:
            st.metric(label, value)
            marker(f"stat-{testid}", value)

    st.divider()
    action_columns = st.columns(2)
    with action_columns[0]:
        if round_obj["status"] == "draft":
            if st.button("Активировать раунд", key="activate_round", type="primary"):
                try:
                    client.admin_activate_round(
                        round_id, session_id, idempotency_key=str(uuid.uuid4())
                    )
                    set_flash("success", "Раунд активирован.")
                except APIClientError as error:
                    set_flash("error", error.message)
                st.rerun()
        else:
            st.caption(f"Статус раунда: {round_obj['status']}")
    with action_columns[1]:
        can_score = round_obj["status"] == "active" and stats["submitted_scenarios"] > 0
        if st.button(
            "Запустить скоринг",
            key="run_scoring",
            type="primary",
            disabled=not can_score or bool(st.session_state.get("pending_command")),
        ):
            st.session_state["pending_command"] = "score"
            try:
                summary = client.admin_trigger_scoring(
                    round_id, session_id, idempotency_key=str(uuid.uuid4())
                )
                set_flash(
                    "success",
                    f"Скоринг завершен: оценено {summary['scored_count']} сценариев "
                    f"за {summary['duration_ms']} мс.",
                )
            except APIClientError as error:
                set_flash("error", error.message)
            finally:
                st.session_state["pending_command"] = None
            st.rerun()
        if not can_score:
            st.caption("Скоринг доступен, когда в активном раунде есть отправленные сценарии.")

    if round_obj.get("scoring_summary"):
        st.json(round_obj["scoring_summary"])


def page_participants() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header("Участники", "Список и цепочки", "Полная цепочка выбранного участника.")
    show_flash()

    round_obj = select_round(client, session_id)
    if not round_obj:
        return
    round_id = round_obj["id"]

    filter_columns = st.columns([2, 1, 1])
    with filter_columns[0]:
        query = st.text_input("Поиск по имени или email", key="participant_query")
    with filter_columns[1]:
        access = st.selectbox("Доступ", ["all", "active", "blocked"], key="participant_access")
    with filter_columns[2]:
        status_filter = st.selectbox(
            "Сценарий", ["all", "none", "draft", "submitted", "scored"],
            key="participant_status",
        )

    page = client.admin_list_participants(
        round_id, query or None, access, status_filter, session_id
    )
    rows = page.get("rows", [])
    marker("participant-count", len(rows))
    if not rows:
        st.info("Участники не найдены.")
        return

    body = "".join(
        "<tr>"
        f"<td>{row['id']}</td>"
        f"<td>{escape(row['display_name'])}</td>"
        f"<td>{escape(row['email'])}</td>"
        f"<td>{escape(STATUS_LABELS.get(row['scenario_status'], row['scenario_status']))}</td>"
        f"<td>{escape(str(row.get('game_score') or '—'))}</td>"
        f"<td>{'заблокирован' if row['is_blocked'] else 'активен'}</td>"
        "</tr>"
        for row in rows
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-table" data-testid="participants-table">'
        "<thead><tr><th>ID</th><th>Участник</th><th>Email</th><th>Сценарий</th>"
        f"<th>Балл</th><th>Доступ</th></tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    st.divider()
    options = {f"#{row['id']} · {row['display_name']}": row for row in rows}
    chosen = st.selectbox("Открыть участника", list(options), key="participant_select")
    selected = options[chosen]
    detail = client.admin_get_participant_detail(round_id, selected["id"], session_id)
    marker("detail-participant-id", detail["user"]["id"])

    scenario = detail.get("scenario")
    if not scenario:
        st.info("У участника ещё нет сценария в этом раунде.")
    else:
        marker("detail-scenario-status", scenario["status"])
        marker("detail-step-count", len(scenario["steps"]))
        st.markdown(
            f"**Сценарий #{scenario['id']}** · статус "
            f"{STATUS_LABELS.get(scenario['status'], scenario['status'])} · "
            f"ревизия {scenario['revision']}"
        )
        step_rows = "".join(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(step['card']['code'])}</td>"
            f"<td>{escape(step['amount'])}</td>"
            f"<td>{step['frequency']}</td>"
            f"<td>{escape(step['context']['channel'])}</td>"
            f"<td>{escape(step['context']['time_of_day'])}</td>"
            "</tr>"
            for index, step in enumerate(scenario["steps"], start=1)
        )
        st.markdown(
            '<div class="aml-scroll"><table class="aml-table" data-testid="chain-table">'
            "<thead><tr><th>#</th><th>Карточка</th><th>Сумма</th><th>Повторы</th>"
            f"<th>Канал</th><th>Время</th></tr></thead><tbody>{step_rows}</tbody></table></div>",
            unsafe_allow_html=True,
        )

    result = detail.get("result")
    if result:
        marker("detail-game-score", result["base"]["game_score"])
        columns = st.columns(3)
        columns[0].metric("Базовый балл", result["base"]["game_score"])
        columns[1].metric("Эффективный балл", result["effective"]["game_score"])
        columns[2].metric("Риск", result["base"]["risk_score"])

    st.divider()
    block_column, adjust_column = st.columns(2)
    with block_column:
        st.markdown("**Доступ участника**")
        blocked = detail["user"]["is_blocked"]
        reason = st.text_input(
            "Основание (не менее 10 символов)", key=f"block_reason_{selected['id']}"
        )
        if st.button(
            "Разблокировать" if blocked else "Заблокировать",
            key="toggle_access",
            use_container_width=True,
        ):
            try:
                client.admin_update_access(
                    round_id,
                    selected["id"],
                    not blocked,
                    reason,
                    detail["user"]["access_revision"],
                    session_id,
                )
                set_flash("success", "Состояние доступа обновлено.")
            except APIClientError as error:
                set_flash("error", error.message)
            st.rerun()

    with adjust_column:
        st.markdown("**Ручная корректировка лидерборда**")
        if not result:
            st.caption("Доступна после скоринга раунда.")
        else:
            current_revision = (result.get("adjustment") or {}).get("revision", 0)
            game_override = st.text_input(
                "Игровой балл (0..100)", key=f"adjust_game_{selected['id']}"
            )
            adjust_reason = st.text_input(
                "Основание корректировки", key=f"adjust_reason_{selected['id']}"
            )
            if st.button("Применить корректировку", key="apply_adjustment", use_container_width=True):
                try:
                    client.admin_adjust_leaderboard(
                        round_id,
                        selected["id"],
                        current_revision,
                        adjust_reason,
                        None,
                        None,
                        game_override or None,
                        session_id,
                    )
                    set_flash("success", "Корректировка сохранена.")
                except APIClientError as error:
                    set_flash("error", error.message)
                st.rerun()
            if current_revision:
                if st.button("Снять корректировку", key="clear_adjustment", use_container_width=True):
                    try:
                        client.admin_clear_leaderboard_adjustment(
                            round_id, selected["id"], session_id, current_revision
                        )
                        set_flash("success", "Корректировка снята.")
                    except APIClientError as error:
                        set_flash("error", error.message)
                    st.rerun()


def page_leaderboard() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header("Лидерборд", "Базовые и эффективные значения", "Заблокированные участники видны только здесь.")
    round_obj = select_round(client, session_id)
    if not round_obj:
        return
    board = client.admin_get_leaderboard(round_obj["id"], session_id)
    rows = board.get("rows", [])
    marker("admin-board-rows", len(rows))
    if not rows:
        st.info("Результаты появятся после скоринга.")
        return
    body = "".join(
        "<tr>"
        f"<td>{row['rank']}</td>"
        f"<td>{escape(row['display_name'])}</td>"
        f"<td>{row['base_game_score']}</td>"
        f"<td>{row['effective_game_score']}</td>"
        f"<td>{row['base_risk_score']}</td>"
        f"<td>{'да' if row['is_adjusted'] else 'нет'}</td>"
        f"<td>{'да' if row['is_blocked'] else 'нет'}</td>"
        "</tr>"
        for row in rows
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-table" data-testid="admin-board-table">'
        "<thead><tr><th>Место</th><th>Участник</th><th>База</th><th>Эффективный</th>"
        f"<th>Риск</th><th>Корректировка</th><th>Блок</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def page_audit() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header("Аудит", "Журнал действий", "Только безопасные метаданные, без PII.")
    round_obj = select_round(client, session_id)
    if not round_obj:
        return
    events = client.admin_get_audit_events(round_obj["id"], session_id).get("rows", [])
    marker("audit-rows", len(events))
    if not events:
        st.info("Событий пока нет.")
        return
    body = "".join(
        "<tr>"
        f"<td>{escape(event['created_at'])}</td>"
        f"<td>{escape(event['event_type'])}</td>"
        f"<td>{escape(str(event.get('target_type') or ''))}</td>"
        f"<td>{escape(str(event.get('reason') or ''))}</td>"
        "</tr>"
        for event in events
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-table" data-testid="audit-table">'
        "<thead><tr><th>Время</th><th>Событие</th><th>Объект</th><th>Основание</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    st.session_state.setdefault("flash", None)
    st.session_state.setdefault("pending_command", None)
    client = get_api_client()
    controller = get_cookie_controller("aml_admin_cookies")
    session = resolve_session(controller, ADMIN_COOKIE, client)

    if session.pending:
        st.info("Восстанавливаем сессию…")
        marker("auth-state", "pending")
        st.stop()
    if not session.authenticated:
        login_screen(client, controller)
        st.stop()

    user = session.user or {}
    with st.sidebar:
        st.markdown("### AML Workshop Control")
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
            clear_session(controller, ADMIN_COOKIE)
            reset_user_state()
            st.rerun()

    navigation = st.navigation(
        [
            st.Page(page_monitoring, title="Мониторинг", url_path="monitoring", default=True),
            st.Page(page_participants, title="Участники", url_path="participants"),
            st.Page(page_leaderboard, title="Лидерборд", url_path="leaderboard"),
            st.Page(page_audit, title="Аудит", url_path="audit"),
        ],
        position="sidebar",
    )
    navigation.run()


main()
