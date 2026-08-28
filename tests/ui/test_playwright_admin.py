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
    clipped_elements,
    click_button,
    expect_marker,
    fill_text,
    has_horizontal_overflow,
    login,
    marker,
)

pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as engine:
        instance = engine.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


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
                step("online_purchase", "100000.00", "web"),
                step("card_transfer", "60000.00", "mobile"),
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
    expect_marker(admin_page, "round-status", "active")


def test_admin_sees_the_full_chain_of_a_participant(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Цепочка")
    submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    admin_page.get_by_role("link", name="Участники").click()
    expect_marker(admin_page, "participant-count", "1", timeout=60_000)
    expect_marker(admin_page, "detail-scenario-status", "submitted")
    expect_marker(admin_page, "detail-step-count", "3")

    table = admin_page.locator('[data-testid="chain-table"]')
    table.wait_for(state="visible", timeout=30_000)
    body = table.text_content() or ""
    for code in ("salary", "online_purchase", "card_transfer"):
        assert code in body
    assert "bank" in body and "web" in body and "mobile" in body


def test_scoring_from_the_admin_ui_publishes_participant_results(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Скоринг")
    prepared = submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    expect_marker(admin_page, "stat-submitted", "1")
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
    admin_page.get_by_role("link", name="Лидерборд").click()
    expect_marker(admin_page, "admin-board-rows", "1", timeout=60_000)
    table = admin_page.locator('[data-testid="admin-board-table"]')
    table.wait_for(state="visible", timeout=30_000)
    assert player["display_name"] in (table.text_content() or "")


def test_block_and_unblock_from_the_admin_ui(reset_state: Stack, admin_page: Any) -> None:
    stack = reset_state
    player = register(stack, "Блокировка")
    prepared = submit_chain_via_api(stack, player)

    admin_login(admin_page, stack)
    admin_page.get_by_role("link", name="Участники").click()
    expect_marker(admin_page, "participant-count", "1", timeout=60_000)
    participant_id = int(marker(admin_page, "detail-participant-id"))

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
    admin_page.get_by_role("link", name="Аудит").click()
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


def test_scoring_button_is_disabled_without_submissions(
    reset_state: Stack, admin_page: Any
) -> None:
    stack = reset_state
    admin_login(admin_page, stack)
    expect_marker(admin_page, "stat-submitted", "0")
    assert button_is_disabled(admin_page, "run_scoring")
