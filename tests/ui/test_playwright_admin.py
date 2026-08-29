"""Browser end-to-end flows for the administrator UI and the full round."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.ui.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ARTIFACTS,
    PARTICIPANT_PASSWORD,
    Stack,
    db_query,
    register,
)
from tests.ui.streamlit_driver import (
    button_is_disabled,
    check,
    clipped_elements,
    click_button,
    expect_flash,
    expect_marker,
    fill_number,
    fill_text,
    has_horizontal_overflow,
    login,
    marker,
    open_page,
    open_tab,
    streamlit_theme_options,
)

pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def admin_page(browser: Any, request: pytest.FixtureRequest) -> Iterator[Any]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    context.tracing.start(screenshots=True, snapshots=True)
    failed_before = request.session.testsfailed
    try:
        yield context.new_page()
    finally:
        name = request.node.name.replace("/", "_")[:80]
        if request.session.testsfailed > failed_before:
            context.tracing.stop(path=str(ARTIFACTS / f"trace-admin-{name}.zip"))
            for index, page in enumerate(context.pages):
                page.screenshot(path=str(ARTIFACTS / f"failure-admin-{name}-{index}.png"))
        else:
            context.tracing.stop()
        context.close()


def admin_login(page: Any, stack: Stack) -> None:
    login(page, stack.admin_url, ADMIN_EMAIL, ADMIN_PASSWORD, admin=True)
    marker(page, "round-id", timeout=60_000)


def submit_chain_via_api(stack: Stack, player: dict[str, str]) -> dict[str, Any]:
    """Prepare a submitted scenario without going through the browser."""
    session = stack.request(
        "POST",
        "/api/v1/auth/login",
        {"email": player["email"], "password": PARTICIPANT_PASSWORD, "audience": "play"},
    )
    session_id = session["session_id"]
    active = stack.request("GET", "/api/v1/rounds/active")
    cards = {card["code"]: card for card in stack.request(
        "GET", f"/api/v1/rounds/{active['id']}/cards"
    )}

    def step(code: str, amount: str, channel: str) -> dict[str, Any]:
        card = cards[code]
        return {
            "step_id": str(uuid.uuid4()),
            "card": {"id": card["id"], "code": card["code"], "version": card["version"]},
            "amount": amount,
            "frequency": 1,
            "context": {"channel": channel},
            "action_details": {field["key"]: field["default"] for field in card["fields"]},
        }

    saved = stack.request(
        "PUT",
        f"/api/v1/rounds/{active['id']}/scenario",
        {
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
            "steps": [
                step("salary", "120000.00", "bank"),
                step("card_transfer", "100000.00", "mobile"),
                step("cash_withdrawal", "50000.00", "atm"),
            ],
        },
        session_id=session_id,
    )
    submitted = stack.request(
        "POST",
        f"/api/v1/rounds/{active['id']}/scenario/submit",
        {"expected_revision": saved["revision"]},
        session_id=session_id,
    )
    return {"round_id": active["id"], "scenario": submitted, "session_id": session_id}


def test_admin_login_and_live_counters(reset_state: Stack, admin_page: Any) -> None:
    stack = reset_state
    player = register(stack, "Мониторинг")
    submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    expect_marker(admin_page, "stat-registered", "1")
    expect_marker(admin_page, "stat-submitted", "1")
    expect_marker(admin_page, "stat-scored", "0")
    expect_marker(admin_page, "stat-versions", "1")
    expect_marker(admin_page, "round-status", "active")
    expect_marker(admin_page, "scoring-can-score", "true")


def test_admin_sees_every_parameter_of_the_submitted_version(
    reset_state: Stack, admin_page: Any
) -> None:
    """Not a printed dict: a labelled block per step, hidden defaults included."""
    stack = reset_state
    player = register(stack, "Цепочка")
    submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    open_page(admin_page, "Участники")
    expect_marker(admin_page, "participant-count", "1", timeout=60_000)
    expect_marker(admin_page, "detail-scenario-status", "submitted")
    expect_marker(admin_page, "detail-step-count", "3")

    open_tab(admin_page, "Версии черновиков")
    expect_marker(admin_page, "versions-count", "1")
    expect_marker(admin_page, "admin-version-revision", "1")
    expect_marker(admin_page, "admin-version-steps", "3")

    blocks = admin_page.locator('[data-testid^="step-params-"]')
    blocks.first.wait_for(state="visible", timeout=30_000)
    assert blocks.count() == 3
    body = "\n".join(blocks.all_text_contents())
    for channel, raw in (
        ("Банковское зачисление", "bank"),
        ("Мобильное приложение", "mobile"),
        ("Банкомат", "atm"),
    ):
        assert channel in body and f"({raw})" in body
    # Parameters the round hides are still recorded and still displayed.
    assert "Есть подтверждающие документы" in body
    assert "Плательщик" in body

    page_body = admin_page.locator('[data-testid="stMain"]').text_content() or ""
    for code in ("salary", "card_transfer", "cash_withdrawal"):
        assert code in page_body
    assert "Ресурсы до" in page_body and "Ресурсы после" in page_body


def test_scoring_from_the_admin_ui_publishes_participant_results(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Скоринг")
    prepared = submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    expect_marker(admin_page, "stat-submitted", "1")
    check(admin_page, "confirm_scoring")
    click_button(admin_page, "run_scoring")
    admin_page.locator('[data-testid="flash-success"]').first.wait_for(
        state="attached", timeout=90_000
    )

    rows = db_query("SELECT count(*) FROM scoring_results")
    assert rows == [(1,)]
    round_status = db_query("SELECT status FROM rounds WHERE id = %s", (prepared["round_id"],))
    assert round_status == [("completed",)]

    result = stack.request(
        "GET",
        f"/api/v1/rounds/{prepared['round_id']}/result",
        session_id=prepared["session_id"],
    )
    assert result is not None
    assert 0 <= float(result["base"]["game_score"]) <= 100

    admin_page.reload(wait_until="domcontentloaded")
    expect_marker(admin_page, "round-status", "completed", timeout=90_000)
    expect_marker(admin_page, "stat-scored", "1")


def test_admin_leaderboard_shows_base_and_effective_values(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Лидерборд")
    prepared = submit_chain_via_api(stack, player)
    admin_session = stack.request(
        "POST",
        "/api/v1/auth/login",
        {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "audience": "admin"},
    )["session_id"]
    stack.request(
        "POST",
        f"/api/v1/admin/rounds/{prepared['round_id']}/score",
        session_id=admin_session,
    )

    admin_login(admin_page, stack)
    open_page(admin_page, "Лидерборд")
    expect_marker(admin_page, "admin-board-rows", "1", timeout=60_000)
    table = admin_page.locator('[data-testid="admin-board-table"]')
    table.wait_for(state="visible", timeout=30_000)
    # The administrator keeps real identities...
    assert player["display_name"] in (table.text_content() or "")
    # ...while the public board of the same round does not.
    public = stack.request("GET", f"/api/v1/rounds/{prepared['round_id']}/leaderboard")
    assert public["rows"][0]["display_name"] == "Игрок #1"
    assert public["revealed"] is False


def test_block_and_unblock_from_the_admin_ui(reset_state: Stack, admin_page: Any) -> None:
    stack = reset_state
    player = register(stack, "Блокировка")
    submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    open_page(admin_page, "Участники")
    expect_marker(admin_page, "participant-count", "1", timeout=60_000)
    participant_id = int(marker(admin_page, "detail-participant-id"))
    open_tab(admin_page, "Доступ и баллы")

    fill_text(admin_page, f"block_reason_{participant_id}", "Проверка учетной записи организатором")
    click_button(admin_page, "toggle_access")
    admin_page.locator('[data-testid="flash-success"]').first.wait_for(
        state="attached", timeout=60_000
    )

    blocked = db_query("SELECT is_blocked FROM users WHERE id = %s", (participant_id,))
    assert blocked == [(True,)]
    revoked = db_query(
        "SELECT count(*) FROM sessions WHERE user_id = %s AND revoked_at IS NULL",
        (participant_id,),
    )
    assert revoked == [(0,)]
    # The scenario itself is untouched by the block.
    steps = db_query(
        "SELECT jsonb_array_length(steps) FROM scenarios WHERE participant_id = %s",
        (participant_id,),
    )
    assert steps == [(3,)]


def test_audit_trail_is_visible_and_free_of_pii(reset_state: Stack, admin_page: Any) -> None:
    stack = reset_state
    player = register(stack, "Аудит")
    submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    open_page(admin_page, "Аудит")
    admin_page.locator('[data-testid="audit-table"]').first.wait_for(
        state="visible", timeout=60_000
    )
    content = admin_page.locator('[data-testid="audit-table"]').text_content() or ""
    assert "round_activated" in content
    assert player["email"] not in content


def test_admin_ui_has_no_overflow_or_clipped_text(reset_state: Stack, admin_page: Any) -> None:
    stack = reset_state
    player = register(stack, "Верстка")
    submit_chain_via_api(stack, player)
    admin_login(admin_page, stack)

    assert not has_horizontal_overflow(admin_page)
    assert clipped_elements(admin_page) == []
    admin_page.screenshot(path=str(ARTIFACTS / "admin-monitoring.png"), full_page=True)


def test_theme_is_only_available_in_streamlit_menu(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    admin_login(admin_page, stack)
    assert admin_page.locator('[class*="st-key-theme_toggle"]').count() == 0
    assert streamlit_theme_options(admin_page) == ["System", "Light", "Dark"]


def test_scoring_button_is_disabled_without_submissions(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    admin_login(admin_page, stack)
    expect_marker(admin_page, "stat-submitted", "0")
    expect_marker(admin_page, "scoring-can-score", "false")
    assert button_is_disabled(admin_page, "run_scoring")
    # Even a confirmed organiser cannot score a round with nothing submitted.
    check(admin_page, "confirm_scoring")
    assert button_is_disabled(admin_page, "run_scoring")


# --------------------------------------------------------------------------
# Presets and the configuration editor
# --------------------------------------------------------------------------


def test_a_preset_can_be_saved_and_turned_into_a_draft_round(
    reset_state: Stack, admin_page: Any
) -> None:
    """Loading a preset prepares a round; it never starts the game by itself."""
    stack = reset_state
    admin_login(admin_page, stack)
    open_page(admin_page, "Раунд и конфигурация")
    open_tab(admin_page, "Создать раунд")

    fill_number(admin_page, "new_target", 200000)
    fill_number(admin_page, "new_max_actions", 6)
    fill_text(admin_page, "new_preset_name", "Короткий мастер-класс")
    fill_text(admin_page, "new_preset_description", "Шесть операций, цель 200 000")
    click_button(admin_page, "save_preset")
    expect_flash(admin_page, "Пресет «Короткий мастер-класс» сохранен")

    presets = db_query("SELECT name, game_config FROM round_presets ORDER BY id")
    assert [row[0] for row in presets] == ["Короткий мастер-класс"]
    assert presets[0][1]["objectives"]["target_outflow"] == "200000.00"
    assert presets[0][1]["objectives"]["max_actions"] == 6

    open_page(admin_page, "Пресеты")
    expect_marker(admin_page, "preset-count", "1", timeout=60_000)
    fill_text(admin_page, "preset_round_title", "Раунд из пресета")
    click_button(admin_page, "round_from_preset")
    expect_flash(admin_page, "создан из пресета")

    rounds = db_query("SELECT title, status, preset_id, game_config FROM rounds ORDER BY id")
    assert len(rounds) == 2, rounds
    title, status, preset_id, config = rounds[1]
    assert title == "Раунд из пресета"
    assert status == "draft", "a preset must never start the round on its own"
    assert preset_id is not None
    assert config["objectives"]["target_outflow"] == "200000.00"

    # Editing the preset afterwards must not touch the round already created.
    fill_number(admin_page, f"preset{preset_id}_target", 90000)
    click_button(admin_page, "update_preset")
    expect_flash(admin_page, "Пресет обновлен")
    assert (
        db_query("SELECT game_config FROM rounds ORDER BY id")[1][0]["objectives"][
            "target_outflow"
        ]
        == "200000.00"
    )
    assert (
        db_query("SELECT game_config FROM round_presets")[0][0]["objectives"][
            "target_outflow"
        ]
        == "90000.00"
    )


def test_a_preset_is_deleted_only_after_confirmation(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    admin_login(admin_page, stack)
    open_page(admin_page, "Раунд и конфигурация")
    open_tab(admin_page, "Создать раунд")
    fill_text(admin_page, "new_preset_name", "Черновой пресет")
    click_button(admin_page, "save_preset")
    expect_flash(admin_page, "Пресет «Черновой пресет» сохранен")

    open_page(admin_page, "Пресеты")
    expect_marker(admin_page, "preset-count", "1", timeout=60_000)
    assert button_is_disabled(admin_page, "delete_preset")

    check(admin_page, "confirm_delete_preset")
    click_button(admin_page, "delete_preset")
    expect_flash(admin_page, "Пресет удален")
    expect_marker(admin_page, "preset-count", "0", timeout=60_000)
    assert db_query("SELECT count(*) FROM round_presets") == [(0,)]
