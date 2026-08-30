"""Administrator Streamlit application.

Reads and writes exclusively through `/api/v1/admin/*`. There is no demo state
and no local store: every number on screen comes from PostgreSQL through
FastAPI. The lifecycle buttons («Начать раунд», «Остановить раунд»,
«Перезапустить раунд», скоринг) are the only way a round changes state, and
each of them is confirmed, idempotent and written to the audit log.
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

from src.aml_workshop_simulator.ui.admin.config_editor import (  # noqa: E402
    render_editor,
)
from src.aml_workshop_simulator.ui.shared.api_client import APIClientError  # noqa: E402
from src.aml_workshop_simulator.ui.shared.session import (  # noqa: E402
    ADMIN_COOKIE,
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
    page_title="AML Workshop Control",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="auto",
)

STYLES = """
<style>
:root, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    --aml-line: var(--border-color);
    --aml-muted: color-mix(in srgb, var(--text-color) 62%, transparent);
}
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
.aml-param-grid {
    display: grid; grid-template-columns: minmax(160px, 1fr) minmax(160px, 1.4fr);
    gap: .15rem .8rem; font-size: 14px; margin: .3rem 0 .6rem;
}
.aml-param-grid .k { color: var(--aml-muted); }
.aml-pill {
    display: inline-block; padding: .1rem .5rem; border-radius: 999px;
    border: 1px solid var(--aml-line); font-size: 12px; margin-right: .3rem;
}
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
    .aml-param-grid { grid-template-columns: 1fr; }
}
</style>
"""

STATUS_LABELS = {
    "draft": "Черновик",
    "submitted": "Отправлен",
    "scored": "Оценен",
    "none": "Нет сценария",
}
ROUND_STATUS_LABELS = {
    "draft": "Черновик — участники ждут",
    "active": "Идет",
    "stopped": "Остановлен",
    "scoring": "Подсчет результатов",
    "completed": "Завершен",
}


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


def money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def login_screen(client: Any) -> None:
    header(
        "AML Workshop Control",
        "Вход администратора",
        "Управление раундом, конфигурацией и скорингом.",
    )
    marker("auth-state", "anonymous")
    show_flash()
    with st.form("admin_login"):
        email = st.text_input("Email", key="admin_email")
        password = st.text_input("Пароль", type="password", key="admin_password")
        submitted = st.form_submit_button("Войти", type="primary", use_container_width=True)
    if submitted:
        # A second click queued while the first request was in flight must not
        # create a second session.
        if st.session_state.get("session_id"):
            st.rerun()
            return
        if st.session_state.get("pending_command"):
            return
        st.session_state["pending_command"] = "login"
        try:
            created = client.login(email.strip(), password, audience="admin")
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

    error_message = st.session_state.pop("auth_error", None)
    if error_message:
        st.error(error_message)
        marker("auth-error", error_message)


def select_round(client: Any, session_id: str, key: str = "admin_round_select"):
    rounds = client.admin_list_rounds(session_id)
    marker("round-count", len(rounds))
    if not rounds:
        st.warning(
            "Раундов пока нет. Создайте первый на вкладке «Раунд и конфигурация»."
        )
        return None
    options = {
        f"#{item['id']} · {item['title']} ({ROUND_STATUS_LABELS.get(item['status'], item['status'])})": item
        for item in rounds
    }
    chosen = st.selectbox("Раунд", list(options), key=key)
    return options[chosen]


# --------------------------------------------------------------------------
# Round configuration and lifecycle
# --------------------------------------------------------------------------


def _reference_config(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Starting point for the very first round of a fresh installation."""
    return get_api_client().admin_default_game_config(st.session_state["session_id"])


def page_round_setup() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header(
        "Раунд",
        "Конфигурация и запуск",
        "Настройте параметры, создайте черновик и запустите раунд явной командой.",
    )
    show_flash()

    catalog = client.admin_get_action_cards(session_id)
    rounds = client.admin_list_rounds(session_id)
    presets = client.admin_list_presets(session_id)
    marker("round-count", len(rounds))
    marker("preset-count", len(presets))

    create_tab, manage_tab = st.tabs(["Создать раунд", "Управление раундом"])

    with create_tab:
        st.markdown("##### Источник конфигурации")
        preset_options: dict[str, dict[str, Any] | None] = {"Базовая конфигурация": None}
        preset_options.update({f"Пресет · {item['name']}": item for item in presets})
        source_name = st.selectbox(
            "Откуда взять настройки", list(preset_options), key="new_round_source"
        )
        source = preset_options[source_name]
        base_config = (
            dict(source["game_config"]) if source else _reference_config(catalog)
        )
        marker("selected-preset", source["id"] if source else "")

        title = st.text_input(
            "Название раунда", value="Новый раунд", key="new_round_title"
        )
        config = render_editor(base_config, catalog, key_prefix="new")
        with st.expander("JSON конфигурации (только для диагностики)", expanded=False):
            st.json(config)

        if st.button(
            "Создать черновик раунда",
            key="create_round",
            type="primary",
            use_container_width=True,
            disabled=bool(st.session_state.get("pending_command")),
        ):
            st.session_state["pending_command"] = "create_round"
            try:
                created = client.admin_create_round(
                    title.strip(), config, session_id, preset_id=None
                )
                set_flash(
                    "success",
                    f"Черновик раунда #{created['id']} создан. Нажмите «Начать раунд», "
                    "чтобы открыть его участникам.",
                )
            except APIClientError as error:
                set_flash("error", error.message)
            finally:
                st.session_state["pending_command"] = None
            st.rerun()

        st.divider()
        st.markdown("##### Сохранить эти настройки как пресет")
        preset_columns = st.columns([2, 3, 1])
        with preset_columns[0]:
            preset_name = st.text_input("Название пресета", key="new_preset_name")
        with preset_columns[1]:
            preset_description = st.text_input("Описание", key="new_preset_description")
        with preset_columns[2]:
            if st.button("Сохранить пресет", key="save_preset", use_container_width=True):
                try:
                    client.admin_create_preset(
                        preset_name.strip(),
                        preset_description.strip() or None,
                        config,
                        session_id,
                    )
                    set_flash("success", f"Пресет «{preset_name}» сохранен.")
                except APIClientError as error:
                    set_flash("error", error.message)
                st.rerun()

    with manage_tab:
        round_obj = select_round(client, session_id, key="setup_round_select")
        if not round_obj:
            return
        round_id = round_obj["id"]
        marker("round-id", round_id)
        marker("round-status", round_obj["status"])
        st.markdown(
            f"**Статус:** {ROUND_STATUS_LABELS.get(round_obj['status'], round_obj['status'])}"
            + (
                f" · перезапуск раунда #{round_obj['restarted_from_round_id']}"
                if round_obj.get("restarted_from_round_id")
                else ""
            )
        )

        if round_obj["status"] == "draft":
            st.caption(
                "Конфигурацию можно менять, пока раунд не запущен. После запуска она "
                "становится неизменяемым снимком."
            )
            edited = render_editor(
                round_obj["game_config"], catalog, key_prefix=f"edit{round_id}"
            )
            edit_columns = st.columns(2)
            with edit_columns[0]:
                if st.button(
                    "Сохранить конфигурацию", key="save_round_config",
                    use_container_width=True,
                ):
                    try:
                        client.admin_update_round(
                            round_id,
                            round_obj["config_revision"],
                            None,
                            edited,
                            session_id,
                        )
                        set_flash("success", "Конфигурация раунда сохранена.")
                    except APIClientError as error:
                        set_flash("error", error.message)
                    st.rerun()
            with edit_columns[1]:
                if st.button(
                    "Начать раунд", key="start_round", type="primary",
                    use_container_width=True,
                    disabled=bool(st.session_state.get("pending_command")),
                ):
                    st.session_state["pending_command"] = "start"
                    try:
                        client.admin_start_round(
                            round_id, session_id, idempotency_key=str(uuid.uuid4())
                        )
                        set_flash("success", "Раунд запущен: участники могут играть.")
                    except APIClientError as error:
                        set_flash("error", error.message)
                    finally:
                        st.session_state["pending_command"] = None
                    st.rerun()
        else:
            with st.expander("Снимок конфигурации раунда", expanded=False):
                st.json(round_obj["game_config"])

        st.divider()
        st.markdown("##### Управление жизненным циклом")
        lifecycle = st.columns(2)
        with lifecycle[0]:
            stop_confirmed = st.checkbox(
                "Подтверждаю остановку раунда", key="confirm_stop"
            )
            if st.button(
                "Остановить раунд",
                key="stop_round",
                use_container_width=True,
                disabled=round_obj["status"] != "active"
                or not stop_confirmed
                or bool(st.session_state.get("pending_command")),
            ):
                st.session_state["pending_command"] = "stop"
                try:
                    client.admin_stop_round(
                        round_id,
                        session_id,
                        confirm=True,
                        reason="Остановлено организатором",
                        idempotency_key=str(uuid.uuid4()),
                    )
                    set_flash(
                        "success",
                        "Раунд остановлен: изменения участников больше не принимаются, "
                        "все данные сохранены.",
                    )
                except APIClientError as error:
                    set_flash("error", error.message)
                finally:
                    st.session_state["pending_command"] = None
                st.rerun()
        with lifecycle[1]:
            restart_confirmed = st.checkbox(
                "Подтверждаю перезапуск раунда", key="confirm_restart"
            )
            st.caption(
                "Перезапуск создаёт новый раунд с той же конфигурацией. Сценарии, "
                "черновики, результаты и журнал прошлого раунда сохраняются."
            )
            if st.button(
                "Перезапустить раунд",
                key="restart_round",
                use_container_width=True,
                disabled=round_obj["status"] in {"scoring"}
                or not restart_confirmed
                or bool(st.session_state.get("pending_command")),
            ):
                st.session_state["pending_command"] = "restart"
                try:
                    created = client.admin_restart_round(
                        round_id,
                        session_id,
                        confirm=True,
                        reason="Перезапуск организатором",
                        idempotency_key=str(uuid.uuid4()),
                    )
                    set_flash(
                        "success",
                        f"Создан раунд #{created['id']} с той же конфигурацией; "
                        f"раунд #{round_id} остановлен и сохранён.",
                    )
                except APIClientError as error:
                    set_flash("error", error.message)
                finally:
                    st.session_state["pending_command"] = None
                st.rerun()


# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------


def page_presets() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header(
        "Пресеты",
        "Заготовки конфигураций",
        "Пресет — только шаблон: раунд получает собственную копию настроек.",
    )
    show_flash()

    catalog = client.admin_get_action_cards(session_id)
    presets = client.admin_list_presets(session_id)
    marker("preset-count", len(presets))
    if not presets:
        st.info(
            "Пресетов пока нет. Сохраните первый на вкладке «Раунд и конфигурация»."
        )
        return

    body = "".join(
        "<tr>"
        f"<td>{escape(item['name'])}</td>"
        f"<td>{escape(item.get('description') or '—')}</td>"
        f"<td>{item['revision']}</td>"
        f"<td>{escape(str(item['updated_at'])[:19].replace('T', ' '))}</td>"
        f"<td>{item['updated_by_user_id']}</td>"
        "</tr>"
        for item in presets
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-table" data-testid="presets-table">'
        "<thead><tr><th>Название</th><th>Описание</th><th>Ревизия</th>"
        f"<th>Изменен</th><th>Автор</th></tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    options = {item["name"]: item for item in presets}
    chosen = st.selectbox("Открыть пресет", list(options), key="preset_select")
    preset = options[chosen]
    marker("selected-preset-id", preset["id"])

    name = st.text_input("Название", value=preset["name"], key="preset_name")
    description = st.text_input(
        "Описание", value=preset.get("description") or "", key="preset_description"
    )
    config = render_editor(preset["game_config"], catalog, key_prefix=f"preset{preset['id']}")

    columns = st.columns(4)
    with columns[0]:
        if st.button("Обновить пресет", key="update_preset", use_container_width=True):
            try:
                client.admin_update_preset(
                    preset["id"],
                    preset["revision"],
                    session_id,
                    name=name.strip(),
                    description=description.strip() or None,
                    game_config=config,
                )
                set_flash("success", "Пресет обновлен.")
            except APIClientError as error:
                set_flash("error", error.message)
            st.rerun()
    with columns[1]:
        if st.button(
            "Сохранить как новый", key="duplicate_preset", use_container_width=True
        ):
            try:
                client.admin_create_preset(
                    f"{name.strip()} (копия)",
                    description.strip() or None,
                    config,
                    session_id,
                )
                set_flash("success", "Пресет сохранен как новый.")
            except APIClientError as error:
                set_flash("error", error.message)
            st.rerun()
    with columns[2]:
        round_title = st.text_input(
            "Название раунда", value=preset["name"], key="preset_round_title"
        )
        if st.button(
            "Создать раунд из пресета", key="round_from_preset", use_container_width=True
        ):
            try:
                created = client.admin_create_round(
                    round_title.strip(), None, session_id, preset_id=preset["id"]
                )
                set_flash(
                    "success",
                    f"Черновик раунда #{created['id']} создан из пресета. "
                    "Запуск выполняется отдельной командой.",
                )
            except APIClientError as error:
                set_flash("error", error.message)
            st.rerun()
    with columns[3]:
        delete_confirmed = st.checkbox("Подтверждаю удаление", key="confirm_delete_preset")
        if st.button(
            "Удалить пресет",
            key="delete_preset",
            use_container_width=True,
            disabled=not delete_confirmed,
        ):
            try:
                client.admin_delete_preset(preset["id"], session_id)
                set_flash("success", "Пресет удален.")
            except APIClientError as error:
                set_flash("error", error.message)
            st.rerun()


# --------------------------------------------------------------------------
# Monitoring and scoring
# --------------------------------------------------------------------------


def page_monitoring() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header(
        "Мониторинг",
        "Состояние раунда",
        "Счётчики читаются напрямую из PostgreSQL.",
    )
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
        ("Версий черновиков", stats["saved_versions"], "versions"),
    )
    for column, (label, value, testid) in zip(columns, tiles, strict=False):
        with column:
            st.metric(label, value)
            marker(f"stat-{testid}", value)

    st.divider()
    plan = client.admin_get_scoring_plan(round_id, session_id)
    marker("scoring-can-score", "true" if plan["can_score"] else "false")
    st.markdown("##### Скоринг раунда")
    st.info(
        f"К подсчету будет принято отправленных сценариев: {plan['submitted_count']}. "
        f"Черновики без отправки будут исключены: {plan['excluded_draft_count']}."
    )
    if plan["blocker"]:
        st.caption(plan["blocker"])
    confirmed = st.checkbox(
        "Подтверждаю запуск подсчета результатов", key="confirm_scoring"
    )
    if st.button(
        "Запустить скоринг",
        key="run_scoring",
        type="primary",
        use_container_width=True,
        disabled=not plan["can_score"]
        or not confirmed
        or bool(st.session_state.get("pending_command")),
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

    if round_obj.get("scoring_summary"):
        st.json(round_obj["scoring_summary"])


# --------------------------------------------------------------------------
# Participants
# --------------------------------------------------------------------------


def render_step_details(step: dict[str, Any]) -> None:
    """Every parameter of one step, including defaults, zeros and `false`."""
    card = step["card"]
    with st.container(border=True):
        st.markdown(
            f"**{step['index']}. {escape(str(card.get('title') or card.get('code')))}**"
            f" · {money(step['amount'])}"
            + (f" × {step['frequency']}" if int(step["frequency"]) > 1 else "")
        )
        st.markdown(
            f'<span class="aml-pill">card_id {escape(str(card.get("id")))}</span>'
            f'<span class="aml-pill">{escape(str(card.get("code")))} v{escape(str(card.get("version")))}</span>'
            f'<span class="aml-pill">step_id {escape(step["step_id"])}</span>'
            + (
                f'<span class="aml-pill">требует {escape(str(card["requires_card_code"]))}</span>'
                if card.get("requires_card_code")
                else ""
            )
            + (
                f'<span class="aml-pill">квота {escape(str(card["quota_category"]))}</span>'
                if card.get("quota_category")
                else ""
            ),
            unsafe_allow_html=True,
        )

        cells = "".join(
            f'<div class="k">{escape(str(row["label"]))}</div>'
            f'<div data-testid="param-{escape(step["step_id"])}-{escape(row["param"])}">'
            f'{escape(str(row["display"]))} '
            f'<span class="k">({escape(str(row["value"]))})</span></div>'
            for row in step["parameters"]
        )
        st.markdown(
            f'<div class="aml-param-grid" data-testid="step-params-{escape(step["step_id"])}">'
            f"{cells}</div>",
            unsafe_allow_html=True,
        )

        before = step.get("resources_before") or {}
        after = step.get("resources_after") or {}
        costs = step.get("costs") or {}
        if before or after:
            st.markdown(
                '<div class="aml-param-grid">'
                f'<div class="k">Оборот шага</div><div>{escape(money(step.get("gross")))} '
                f'(комиссия {escape(money(step.get("fee")))})</div>'
                f'<div class="k">Изменение баланса</div><div>{escape(money(costs.get("money_delta")))}</div>'
                f'<div class="k">Энергия / время</div>'
                f'<div>−{escape(str(costs.get("energy")))} / −{escape(str(costs.get("time")))}</div>'
                f'<div class="k">Ресурсы до</div><div>{escape(money(before.get("balance")))} · '
                f'{escape(str(before.get("energy")))} · {escape(str(before.get("time")))}</div>'
                f'<div class="k">Ресурсы после</div><div>{escape(money(after.get("balance")))} · '
                f'{escape(str(after.get("energy")))} · {escape(str(after.get("time")))}</div>'
                "</div>",
                unsafe_allow_html=True,
            )
        with st.expander("Исходный JSON шага", expanded=False):
            st.json(step)


def page_participants() -> None:
    client = get_api_client()
    session_id = st.session_state["session_id"]
    header(
        "Участники",
        "Черновики, параметры и сессии",
        "Полная история версий каждого участника и технические данные входа.",
    )
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
            "Сценарий",
            ["all", "none", "draft", "submitted", "scored"],
            key="participant_status",
        )

    # Pages accumulate: an organiser scanning a room of 500 needs the whole
    # roster on one screen, and changing a filter starts the scan over.
    filters = (round_id, query or "", access, status_filter)
    state = st.session_state.get("participants_page")
    if not state or state["filters"] != filters:
        first = client.admin_list_participants(
            round_id, query or None, access, status_filter, session_id
        )
        state = {
            "filters": filters,
            "rows": first.get("rows", []),
            "cursor": first.get("next_cursor"),
        }
        st.session_state["participants_page"] = state

    rows = state["rows"]
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
        f"<td>{row['version_count']}</td>"
        f"<td>{escape(str(row.get('game_score') or '—'))}</td>"
        f"<td>{'заблокирован' if row['is_blocked'] else 'активен'}</td>"
        "</tr>"
        for row in rows
    )
    st.markdown(
        '<div class="aml-scroll"><table class="aml-table" data-testid="participants-table">'
        "<thead><tr><th>ID</th><th>Участник</th><th>Email</th><th>Сценарий</th>"
        f"<th>Версий</th><th>Балл</th><th>Доступ</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    if state["cursor"]:
        if st.button(
            f"Показать ещё · загружено {len(rows)}",
            key="participants_more",
            use_container_width=True,
        ):
            more = client.admin_list_participants(
                round_id,
                query or None,
                access,
                status_filter,
                session_id,
                cursor=state["cursor"],
            )
            state["rows"] = [*rows, *more.get("rows", [])]
            state["cursor"] = more.get("next_cursor")
            st.rerun()

    st.divider()
    options = {f"#{row['id']} · {row['display_name']}": row for row in rows}
    chosen = st.selectbox("Открыть участника", list(options), key="participant_select")
    selected = options[chosen]
    detail = client.admin_get_participant_detail(round_id, selected["id"], session_id)
    marker("detail-participant-id", detail["user"]["id"])

    scenario_tab, versions_tab, sessions_tab, access_tab = st.tabs(
        ["Сценарий", "Версии черновиков", "Сессии и устройства", "Доступ и баллы"]
    )

    scenario = detail.get("scenario")
    with scenario_tab:
        if not scenario:
            st.info("У участника ещё нет сценария в этом раунде.")
        else:
            marker("detail-scenario-status", scenario["status"])
            marker("detail-step-count", len(scenario["steps"]))
            marker("detail-version-count", scenario["version_count"])
            st.markdown(
                f"**Сценарий #{scenario['id']}** · статус "
                f"{STATUS_LABELS.get(scenario['status'], scenario['status'])} · "
                f"текущая версия {scenario['revision']} · "
                f"сохранённых версий {scenario['version_count']}"
            )
            resources = scenario.get("resources") or {}
            after = resources.get("resources_after") or {}
            if after:
                metric_columns = st.columns(4)
                metric_columns[0].metric("Баланс", money(after.get("balance")))
                metric_columns[1].metric("Энергия", after.get("energy"))
                metric_columns[2].metric("Время", after.get("time"))
                metric_columns[3].metric(
                    "Доступных шагов", after.get("available_steps")
                )

    with versions_tab:
        versions = detail.get("versions") or []
        marker("versions-count", len(versions))
        if not versions:
            st.info("Сохранённых версий пока нет.")
        else:
            body = "".join(
                "<tr>"
                f"<td>{item['revision']}</td>"
                f"<td>{escape(item.get('label') or '—')}</td>"
                f"<td>{item['step_count']}</td>"
                f"<td>{escape(money(item.get('balance_after')))}</td>"
                f"<td>{escape(str(item['created_at'])[:19].replace('T', ' '))}</td>"
                f"<td>{'текущая' if item['is_current'] else ''}"
                f"{' отправлена' if item['is_submitted'] else ''}</td>"
                "</tr>"
                for item in versions
            )
            st.markdown(
                '<div class="aml-scroll"><table class="aml-table" data-testid="admin-versions-table">'
                "<thead><tr><th>Версия</th><th>Название</th><th>Шагов</th><th>Баланс после</th>"
                f"<th>Сохранена</th><th>Метки</th></tr></thead><tbody>{body}</tbody></table></div>",
                unsafe_allow_html=True,
            )
            version_options = {
                f"Версия {item['revision']}"
                + (f" · {item['label']}" if item.get("label") else "")
                + (" · отправлена" if item["is_submitted"] else ""): item
                for item in versions
            }
            picked = st.selectbox(
                "Открыть версию", list(version_options), key="admin_version_select"
            )
            revision = version_options[picked]["revision"]
            try:
                version = client.admin_get_participant_version(
                    round_id, selected["id"], revision, session_id
                )
            except APIClientError as error:
                st.error(error.message)
                return
            marker("admin-version-revision", version["revision"])
            marker("admin-version-steps", len(version["described_steps"]))
            st.caption(
                f"Версия {version['revision']} · шагов {version['step_count']} · "
                f"{'без нарушений' if version['valid'] else 'с нарушениями'} · "
                f"{'цель достигнута' if version['goal_reached'] else 'цель не достигнута'}"
            )
            for step in version["described_steps"]:
                render_step_details(step)
            with st.expander("Полный JSON версии", expanded=False):
                st.json(version["resources"])

    with sessions_tab:
        user = detail["user"]
        marker("session-count", len(detail.get("sessions") or []))
        info_columns = st.columns(4)
        info_columns[0].metric("Активных сессий", user["active_session_count"])
        info_columns[1].metric("Всего входов", user["total_session_count"])
        info_columns[2].metric(
            "Зарегистрирован", str(user["created_at"])[:10]
        )
        info_columns[3].metric(
            "Последний вход", str(user.get("last_login_at") or "—")[:19].replace("T", " ")
        )
        st.caption(
            f"Первый вход: {str(user.get('first_login_at') or '—')[:19].replace('T', ' ')} · "
            f"последний IP: {user.get('last_ip_address') or '—'}"
        )
        marker("detail-last-ip", user.get("last_ip_address") or "")
        sessions = detail.get("sessions") or []
        if not sessions:
            st.info("Входов ещё не было.")
        else:
            body = "".join(
                "<tr>"
                f"<td>{escape(str(item['created_at'])[:19].replace('T', ' '))}</td>"
                f"<td>{escape(item['audience'])}</td>"
                f"<td>{escape(item.get('ip_address') or '—')}</td>"
                f"<td>{escape((item.get('user_agent') or '—')[:80])}</td>"
                f"<td>{escape(item.get('accept_language') or '—')}</td>"
                f"<td>{escape(str(item['last_seen_at'])[:19].replace('T', ' '))}</td>"
                f"<td>{'активна' if item['is_active'] else (item.get('revoke_reason') or 'истекла')}</td>"
                "</tr>"
                for item in sessions
            )
            st.markdown(
                '<div class="aml-scroll"><table class="aml-table" data-testid="sessions-table">'
                "<thead><tr><th>Вход</th><th>Интерфейс</th><th>IP</th><th>User-Agent</th>"
                f"<th>Язык</th><th>Активность</th><th>Статус</th></tr></thead>"
                f"<tbody>{body}</tbody></table></div>",
                unsafe_allow_html=True,
            )

    with access_tab:
        result = detail.get("result")
        if result:
            marker("detail-game-score", result["base"]["game_score"])
            columns = st.columns(3)
            columns[0].metric("Базовый балл", result["base"]["game_score"])
            columns[1].metric("Эффективный балл", result["effective"]["game_score"])
            columns[2].metric("Риск", result["base"]["risk_score"])

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
                if st.button(
                    "Применить корректировку",
                    key="apply_adjustment",
                    use_container_width=True,
                ):
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
                    if st.button(
                        "Снять корректировку",
                        key="clear_adjustment",
                        use_container_width=True,
                    ):
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
    header(
        "Лидерборд",
        "Базовые и эффективные значения",
        "Административный вид: настоящие имена и заблокированные участники видны здесь.",
    )
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
    header(
        "Аудит",
        "Журнал действий",
        "Только безопасные метаданные, без PII.",
    )
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
    apply_pending_cookie_command(controller, ADMIN_COOKIE)
    st.markdown(STYLES, unsafe_allow_html=True)

    session = resolve_session(controller, ADMIN_COOKIE, client)
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
            queue_cookie_clear()
            reset_user_state()
            st.rerun()

    navigation = st.navigation(
        [
            st.Page(page_monitoring, title="Мониторинг", url_path="monitoring", default=True),
            st.Page(page_round_setup, title="Раунд и конфигурация", url_path="round"),
            st.Page(page_presets, title="Пресеты", url_path="presets"),
            st.Page(page_participants, title="Участники", url_path="participants"),
            st.Page(page_leaderboard, title="Лидерборд", url_path="leaderboard"),
            st.Page(page_audit, title="Аудит", url_path="audit"),
        ],
        position="sidebar",
    )
    navigation.run()


main()
