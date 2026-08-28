"""Browser end-to-end flows for the participant UI.

Every test drives the real Streamlit app in Chromium and then verifies the
outcome in the API and in PostgreSQL, so a green test means the chain really
travelled browser -> Streamlit -> FastAPI -> PostgreSQL and back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.ui.conftest import (
    ARTIFACTS,
    PARTICIPANT_PASSWORD,
    Stack,
    db_query,
    register,
)
from tests.ui.streamlit_driver import (
    button_is_disabled,
    choose_option,
    clipped_elements,
    click_button,
    expect_marker,
    expect_marker_at_least,
    fill_number,
    has_horizontal_overflow,
    login,
    logout,
    marker,
    marker_locator,
    open_app,
    select_options,
)
from tests.ui.streamlit_driver import register as register_in_ui

playwright_api = pytest.importorskip("playwright.sync_api")

EXPECTED_CHANNEL_LABELS = {
    "Получить зарплату": ["Банковское зачисление", "Отделение банка", "Мобильное приложение"],
    "Внести наличные": ["Банкомат", "Отделение банка"],
    "Перевести по карте": ["Мобильное приложение", "Интернет-банк", "Отделение банка"],
    "Международный перевод": ["Интернет-банк", "Отделение банка"],
    "Снять наличные": ["Банкомат", "Отделение банка"],
    "Купить криптовалюту": ["Криптобиржа", "Интернет-банк"],
    "Оплатить покупку": ["Мобильное приложение", "Интернет-банк"],
    "Получить возврат": ["Мобильное приложение", "Интернет-банк"],
}

ALL_CHANNEL_LABELS = {
    "Банковское зачисление",
    "Отделение банка",
    "Банкомат",
    "Мобильное приложение",
    "Интернет-банк",
    "Криптобиржа",
    "POS-терминал",
}


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
def context(browser: Any, request: pytest.FixtureRequest) -> Iterator[Any]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    instance = browser.new_context(viewport={"width": 1440, "height": 960})
    instance.tracing.start(screenshots=True, snapshots=True)
    failed_before = request.session.testsfailed
    try:
        yield instance
    finally:
        failed = request.session.testsfailed > failed_before
        name = request.node.name.replace("/", "_")[:80]
        if failed:
            instance.tracing.stop(path=str(ARTIFACTS / f"trace-{name}.zip"))
            for index, page in enumerate(instance.pages):
                page.screenshot(path=str(ARTIFACTS / f"failure-{name}-{index}.png"))
        else:
            instance.tracing.stop()
        instance.close()


@pytest.fixture()
def page(context: Any) -> Any:
    return context.new_page()


def participant_login(page: Any, stack: Stack, email: str) -> None:
    """Log in and wait until the scenario builder has finished its first render."""
    login(page, stack.play_url, email, PARTICIPANT_PASSWORD)
    marker(page, "chain-length", timeout=60_000)


def add_step(
    page: Any,
    card_label: str,
    channel_label: str | None = None,
    amount: float | None = None,
    frequency: int | None = None,
    card_code: str | None = None,
    context_choices: dict[str, str] | None = None,
) -> None:
    """Configure one operation in the builder and add it to the chain."""
    before = int(marker(page, "chain-length"))
    choose_option(page, "builder_card", card_label)
    code = card_code or ""
    if amount is not None:
        fill_number(page, f"builder_{code}_amount", amount)
    if frequency is not None:
        fill_number(page, f"builder_{code}_frequency", frequency)
    if channel_label is not None:
        choose_option(page, f"builder_{code}_channel", channel_label)
    for field_key, label in (context_choices or {}).items():
        choose_option(page, f"builder_{code}_ctx_{field_key}", label)
    click_button(page, "add_step")
    expect_marker(page, "chain-length", str(before + 1))


def build_valid_chain(page: Any) -> None:
    add_step(page, "Получить зарплату", "Банковское зачисление", 120000, 1, "salary")
    add_step(page, "Оплатить покупку", "Интернет-банк", 100000, 1, "online_purchase")
    add_step(page, "Перевести по карте", "Мобильное приложение", 60000, 1, "card_transfer")


# --------------------------------------------------------------------------
# Registration, login, session
# --------------------------------------------------------------------------


def test_registration_and_login_through_the_browser(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    email = f"ui{uuid.uuid4().hex[:8]}@example.com"
    register_in_ui(page, stack.play_url, email, "Браузерный участник", PARTICIPANT_PASSWORD)
    assert db_query("SELECT count(*) FROM users WHERE email = %s", (email,))[0][0] == 1

    login(page, stack.play_url, email, PARTICIPANT_PASSWORD)
    assert marker(page, "auth-state") == "authenticated"
    assert "Браузерный участник" in (
        marker_locator(page, "current-user").first.text_content() or ""
    )
    sessions = db_query(
        "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE u.email = %s AND s.revoked_at IS NULL",
        (email,),
    )
    assert sessions[0][0] == 1


def test_login_with_a_wrong_password_shows_an_error(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    player = register(stack, "Ошибочный вход")
    open_app(page, stack.play_url)
    from tests.ui.streamlit_driver import fill_text

    fill_text(page, "login_email", player["email"])
    fill_text(page, "login_password", "definitely-wrong")
    page.get_by_role("button", name="Войти", exact=True).click()
    message = marker(page, "flash-error", timeout=60_000)
    assert "Неверный email или пароль" in message
    assert marker(page, "auth-state") == "anonymous"


# --------------------------------------------------------------------------
# Card contract in the browser
# --------------------------------------------------------------------------


@pytest.mark.parametrize("card_label", sorted(EXPECTED_CHANNEL_LABELS))
def test_channel_selector_offers_exactly_the_allowed_channels(
    reset_state: Stack, page: Any, card_label: str
) -> None:
    stack = reset_state
    player = register(stack, "Каналы")
    participant_login(page, stack, player["email"])

    code = {
        "Получить зарплату": "salary",
        "Внести наличные": "cash_deposit",
        "Перевести по карте": "card_transfer",
        "Международный перевод": "international",
        "Снять наличные": "cash_withdrawal",
        "Купить криптовалюту": "crypto_exchange",
        "Оплатить покупку": "online_purchase",
        "Получить возврат": "refund",
    }[card_label]

    choose_option(page, "builder_card", card_label)
    offered = select_options(page, f"builder_{code}_channel")
    expected = EXPECTED_CHANNEL_LABELS[card_label]
    assert offered == expected, (card_label, offered)
    forbidden = ALL_CHANNEL_LABELS - set(expected)
    assert not (set(offered) & forbidden)
    assert "POS-терминал" not in offered


def test_every_allowed_channel_of_every_card_can_be_added_and_saved(
    reset_state: Stack, page: Any
) -> None:
    """One step per card/channel pair, each saved through the real UI."""
    stack = reset_state
    codes = {
        "Получить зарплату": "salary",
        "Внести наличные": "cash_deposit",
        "Перевести по карте": "card_transfer",
        "Международный перевод": "international",
        "Снять наличные": "cash_withdrawal",
        "Купить криптовалюту": "crypto_exchange",
        "Оплатить покупку": "online_purchase",
        "Получить возврат": "refund",
    }
    for card_label, channels in EXPECTED_CHANNEL_LABELS.items():
        for channel_label in channels:
            player = register(stack, "Канал")
            participant_login(page, stack, player["email"])
            code = codes[card_label]
            if code == "refund":
                add_step(page, "Оплатить покупку", "Интернет-банк", 20000, 1, "online_purchase")
            add_step(page, card_label, channel_label, None, None, code)
            click_button(page, "save_draft")
            expect_marker(page, "scenario-revision", "1")

            stored = db_query(
                "SELECT s.steps FROM scenarios s JOIN users u ON u.id = s.participant_id "
                "WHERE u.email = %s",
                (player["email"],),
            )
            channels_stored = [step["context"]["channel"] for step in stored[0][0]]
            assert channels_stored[-1] in {
                "bank", "branch", "atm", "mobile", "web", "exchange",
            }
            logout(page)


# --------------------------------------------------------------------------
# Chain editing
# --------------------------------------------------------------------------


def test_build_save_and_restore_a_draft_across_logout(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    player = register(stack, "Черновик")
    participant_login(page, stack, player["email"])

    build_valid_chain(page)
    assert marker(page, "scenario-status") == "none"
    click_button(page, "save_draft")
    expect_marker(page, "scenario-status", "draft")
    expect_marker(page, "scenario-revision", "1")
    expect_marker(page, "resources-valid", "true")
    expect_marker(page, "objective-reached", "true")

    rows = db_query(
        "SELECT s.revision, s.status, jsonb_array_length(s.steps) "
        "FROM scenarios s JOIN users u ON u.id = s.participant_id WHERE u.email = %s",
        (player["email"],),
    )
    assert rows == [(1, "draft", 3)]

    logout(page)
    participant_login(page, stack, player["email"])
    expect_marker(page, "chain-length", "3")
    expect_marker(page, "scenario-revision", "1")


def test_draft_survives_a_page_refresh(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    player = register(stack, "Обновление")
    participant_login(page, stack, player["email"])
    build_valid_chain(page)
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")

    page.reload(wait_until="domcontentloaded")
    expect_marker(page, "auth-state", "authenticated", timeout=60_000)
    expect_marker(page, "chain-length", "3")


def test_draft_survives_restarting_api_and_streamlit(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    player = register(stack, "Перезапуск")
    participant_login(page, stack, player["email"])
    build_valid_chain(page)
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")

    stack.restart_api()
    stack.restart_play()

    page.reload(wait_until="domcontentloaded")
    expect_marker(page, "auth-state", "authenticated", timeout=90_000)
    expect_marker(page, "chain-length", "3", timeout=90_000)
    expect_marker(page, "scenario-revision", "1")


def test_edit_delete_reorder_and_duplicate_keep_step_identity(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Редактирование")
    participant_login(page, stack, player["email"])
    build_valid_chain(page)
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")

    def stored_steps() -> list[dict[str, Any]]:
        rows = db_query(
            "SELECT s.steps FROM scenarios s JOIN users u ON u.id = s.participant_id "
            "WHERE u.email = %s",
            (player["email"],),
        )
        return rows[0][0]

    original = stored_steps()
    ids = [step["step_id"] for step in original]

    # Reorder: identity must survive.
    click_button(page, f"up_{ids[2]}")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "2")
    reordered = stored_steps()
    assert [step["step_id"] for step in reordered] == [ids[0], ids[2], ids[1]]

    # Duplicate: a new identity, same content.
    click_button(page, f"copy_{ids[0]}")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "3")
    duplicated = stored_steps()
    assert len(duplicated) == 4
    new_ids = [step["step_id"] for step in duplicated]
    assert len(set(new_ids)) == 4
    assert duplicated[1]["card"]["code"] == duplicated[0]["card"]["code"]
    assert duplicated[1]["step_id"] != duplicated[0]["step_id"]

    # Delete: the remaining identities are untouched.
    click_button(page, f"delete_{duplicated[1]['step_id']}")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "4")
    remaining = stored_steps()
    assert [step["step_id"] for step in remaining] == [ids[0], ids[2], ids[1]]


# --------------------------------------------------------------------------
# Violations and recovery
# --------------------------------------------------------------------------


def test_business_violation_is_shown_per_step_and_blocks_submit(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Нарушение")
    participant_login(page, stack, player["email"])

    add_step(page, "Перевести по карте", "Мобильное приложение", 400000, 1, "card_transfer")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")
    expect_marker(page, "resources-valid", "false")
    expect_marker_at_least(page, "violation-count", 1)

    violation = page.locator('[data-testid="violation-insufficient_balance"]').first
    violation.wait_for(state="visible", timeout=30_000)
    text = violation.text_content() or ""
    assert "Шаг 1" in text
    assert "Сумма" in text
    assert "Уменьшите сумму" in text

    steps = db_query(
        "SELECT s.steps, s.resource_snapshot FROM scenarios s "
        "JOIN users u ON u.id = s.participant_id WHERE u.email = %s",
        (player["email"],),
    )
    assert steps[0][1]["valid"] is False
    expect_marker(page, "submit-enabled", "false")
    assert button_is_disabled(page, "submit_scenario")

    step_id = steps[0][0][0]["step_id"]
    field_error = page.locator(f'[data-testid="step-error-{step_id}-amount"]').first
    field_error.wait_for(state="visible", timeout=30_000)


def test_fixing_a_violation_enables_submit_and_completes_the_round(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Исправление")
    participant_login(page, stack, player["email"])

    # A chain that is structurally fine but breaks the crypto quota.
    add_step(page, "Получить зарплату", "Банковское зачисление", 150000, 1, "salary")
    add_step(page, "Купить криптовалюту", "Криптобиржа", 100000, 1, "crypto_exchange")
    add_step(page, "Оплатить покупку", "Интернет-банк", 60000, 1, "online_purchase")
    add_step(page, "Купить криптовалюту", "Криптобиржа", 50000, 1, "crypto_exchange")
    click_button(page, "save_draft")
    expect_marker(page, "resources-valid", "false")
    page.locator('[data-testid="violation-category_limit_exceeded"]').first.wait_for(
        state="visible", timeout=30_000
    )
    assert button_is_disabled(page, "submit_scenario")

    steps = db_query(
        "SELECT s.steps FROM scenarios s JOIN users u ON u.id = s.participant_id "
        "WHERE u.email = %s",
        (player["email"],),
    )[0][0]
    click_button(page, f"delete_{steps[3]['step_id']}")
    add_step(page, "Перевести по карте", "Мобильное приложение", 50000, 1, "card_transfer")
    click_button(page, "save_draft")
    expect_marker(page, "resources-valid", "true")
    expect_marker(page, "objective-reached", "true")
    expect_marker(page, "submit-enabled", "true")

    click_button(page, "submit_scenario")
    expect_marker(page, "scenario-status", "submitted")
    status = db_query(
        "SELECT s.status FROM scenarios s JOIN users u ON u.id = s.participant_id "
        "WHERE u.email = %s",
        (player["email"],),
    )
    assert status == [("submitted",)]


def test_submit_is_blocked_until_the_objective_is_reached(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Цель")
    participant_login(page, stack, player["email"])
    add_step(page, "Оплатить покупку", "Интернет-банк", 50000, 1, "online_purchase")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")
    expect_marker(page, "resources-valid", "true")
    expect_marker(page, "objective-reached", "false")
    expect_marker(page, "submit-enabled", "false")
    assert button_is_disabled(page, "submit_scenario")


def test_submitted_scenario_is_locked_in_the_ui(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    player = register(stack, "Зафиксировано")
    participant_login(page, stack, player["email"])
    build_valid_chain(page)
    click_button(page, "save_draft")
    click_button(page, "submit_scenario")
    expect_marker(page, "scenario-status", "submitted")

    assert page.locator(".st-key-add_step").count() == 0
    assert page.locator(".st-key-save_draft").count() == 0
    page.reload(wait_until="domcontentloaded")
    expect_marker(page, "scenario-status", "submitted", timeout=60_000)


# --------------------------------------------------------------------------
# Isolation between two participants
# --------------------------------------------------------------------------


def test_two_participants_in_separate_contexts_stay_isolated(
    reset_state: Stack, browser: Any
) -> None:
    stack = reset_state
    first = register(stack, "Первый участник")
    second = register(stack, "Второй участник")

    context_a = browser.new_context(viewport={"width": 1440, "height": 960})
    context_b = browser.new_context(viewport={"width": 1440, "height": 960})
    try:
        page_a = context_a.new_page()
        page_b = context_b.new_page()

        participant_login(page_a, stack, first["email"])
        participant_login(page_b, stack, second["email"])

        add_step(page_a, "Получить зарплату", "Банковское зачисление", 100000, 1, "salary")
        click_button(page_a, "save_draft")
        expect_marker(page_a, "chain-length", "1")

        add_step(page_b, "Оплатить покупку", "Интернет-банк", 30000, 1, "online_purchase")
        add_step(page_b, "Перевести по карте", "Мобильное приложение", 10000, 1, "card_transfer")
        click_button(page_b, "save_draft")
        expect_marker(page_b, "chain-length", "2")

        page_a.reload(wait_until="domcontentloaded")
        expect_marker(page_a, "chain-length", "1", timeout=60_000)
        assert (
            marker_locator(page_a, "current-user").first.text_content().strip()
            == "Первый участник"
        )
        assert (
            marker_locator(page_b, "current-user").first.text_content().strip()
            == "Второй участник"
        )

        rows = db_query(
            "SELECT u.display_name, jsonb_array_length(s.steps) FROM scenarios s "
            "JOIN users u ON u.id = s.participant_id ORDER BY u.display_name"
        )
        assert rows == [("Второй участник", 2), ("Первый участник", 1)]
    finally:
        context_a.close()
        context_b.close()


def test_logout_clears_the_session_and_the_visible_chain(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Выход")
    participant_login(page, stack, player["email"])
    build_valid_chain(page)
    click_button(page, "save_draft")
    logout(page)

    assert page.locator(".st-key-add_step").count() == 0
    assert "120 000" not in (page.content() or "")
    revoked = db_query(
        "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE u.email = %s AND s.revoked_at IS NULL",
        (player["email"],),
    )
    assert revoked == [(0,)]
    assert page.evaluate("() => document.cookie").find("aml_play_session_id") == -1


# --------------------------------------------------------------------------
# Responsive and theme smoke matrix
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height"),
    [(360, 800), (768, 1024), (1366, 768), (1920, 1080)],
    ids=["mobile", "tablet", "laptop", "desktop"],
)
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_responsive_and_theme_smoke(
    reset_state: Stack, browser: Any, width: int, height: int, scheme: str
) -> None:
    stack = reset_state
    player = register(stack, "Адаптив")
    context = browser.new_context(
        viewport={"width": width, "height": height}, color_scheme=scheme
    )
    try:
        page = context.new_page()
        participant_login(page, stack, player["email"])
        add_step(page, "Получить зарплату", "Банковское зачисление", 120000, 1, "salary")
        click_button(page, "save_draft")
        expect_marker(page, "scenario-revision", "1")

        assert not has_horizontal_overflow(page), (width, scheme)
        assert clipped_elements(page) == [], (width, scheme)
        page.screenshot(
            path=str(ARTIFACTS / f"participant-{width}x{height}-{scheme}.png"),
            full_page=True,
        )
    finally:
        context.close()
