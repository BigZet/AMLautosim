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

# The guard must precede the driver import: `streamlit_driver` imports
# playwright at module level, and an ImportError during collection aborts
# the whole pytest session instead of skipping these two files.
playwright_api = pytest.importorskip("playwright.sync_api")

from tests.ui.streamlit_driver import (  # noqa: E402
    DEFAULT_TIMEOUT,
    button_is_disabled,
    choose_option,
    click_button,
    clipped_elements,
    expect_marker,
    expect_marker_at_least,
    fill_number,
    fill_text,
    has_horizontal_overflow,
    login,
    logout,
    marker,
    marker_locator,
    open_app,
    open_tab,
    select_options,
    widget,
)
from tests.ui.streamlit_driver import register as register_in_ui  # noqa: E402

#: The four operations a default round enables, with the channels each offers.
EXPECTED_CHANNEL_LABELS = {
    "Получить зарплату": ["Банковское зачисление", "Отделение банка", "Мобильное приложение"],
    "Внести наличные": ["Банкомат", "Отделение банка"],
    "Перевести по карте": ["Мобильное приложение", "Интернет-банк", "Отделение банка"],
    "Снять наличные": ["Банкомат", "Отделение банка"],
}

CODES = {
    "Получить зарплату": "salary",
    "Внести наличные": "cash_deposit",
    "Перевести по карте": "card_transfer",
    "Снять наличные": "cash_withdrawal",
}

#: Exactly what each operation exposes: the channel plus one more parameter.
EXPECTED_VISIBLE_PARAMS = {
    "salary": "channel,context.time_of_day",
    "cash_deposit": "channel,action.funds_source",
    "card_transfer": "channel,context.recipient_type",
    "cash_withdrawal": "channel,context.time_of_day",
}

ALL_CHANNEL_LABELS = {
    "Банковское зачисление",
    "Отделение банка",
    "Банкомат",
    "Мобильное приложение",
    "Интернет-банк",
}


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


def expect_step_order(page: Any, step_ids: list[str]) -> None:
    """Wait until the chain renders exactly these steps in this order."""
    expected = [f"step-card-{step_id}" for step_id in step_ids]
    page.wait_for_function(
        """(expected) => {
            const seen = [...document.querySelectorAll('[data-testid^="step-card-"]')]
                .filter(node => !node.closest('[data-stale="true"]'))
                .map(node => node.getAttribute('data-testid'));
            return JSON.stringify(seen) === JSON.stringify(expected);
        }""",
        arg=expected,
        timeout=DEFAULT_TIMEOUT,
    )


def build_valid_chain(page: Any) -> None:
    """Salary in, transfer out, cash out: exactly the 150 000 target outflow."""
    add_step(page, "Получить зарплату", "Банковское зачисление", 120000, None, "salary")
    add_step(page, "Перевести по карте", "Мобильное приложение", 100000, 1, "card_transfer")
    add_step(page, "Снять наличные", "Банкомат", 50000, 1, "cash_withdrawal")


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
    open_tab(page, "Вход")

    fill_text(page, "login_email", player["email"])
    fill_text(page, "login_password", "definitely-wrong")
    page.get_by_role("button", name="Войти", exact=True).click()
    message = marker(page, "auth-error", timeout=60_000)
    assert "Неверный email или пароль" in message
    assert marker(page, "auth-state") == "anonymous"
    assert db_query(
        "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE u.email = %s AND s.revoked_at IS NULL",
        (player["email"],),
    ) == [(0,)]


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

    code = CODES[card_label]

    choose_option(page, "builder_card", card_label)
    offered = select_options(page, f"builder_{code}_channel")
    expected = EXPECTED_CHANNEL_LABELS[card_label]
    assert offered == expected, (card_label, offered)
    forbidden = ALL_CHANNEL_LABELS - set(expected)
    assert not (set(offered) & forbidden)


def test_every_allowed_channel_of_every_card_can_be_added_and_saved(
    reset_state: Stack, page: Any
) -> None:
    """One step per card/channel pair, each saved through the real UI."""
    stack = reset_state
    for card_label, channels in EXPECTED_CHANNEL_LABELS.items():
        for channel_label in channels:
            player = register(stack, "Канал")
            participant_login(page, stack, player["email"])
            code = CODES[card_label]
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
                "bank", "branch", "atm", "mobile", "web",
            }
            logout(page)


def test_the_builder_offers_exactly_the_operations_of_the_round(
    reset_state: Stack, page: Any
) -> None:
    """Exactly four operations are available to the participant."""
    stack = reset_state
    player = register(stack, "Каталог раунда")
    participant_login(page, stack, player["email"])

    offered = select_options(page, "builder_card")
    titles = [label.split(" · ")[0] for label in offered]
    assert sorted(titles) == sorted(EXPECTED_CHANNEL_LABELS), offered


@pytest.mark.parametrize("card_label", sorted(EXPECTED_CHANNEL_LABELS))
def test_an_operation_exposes_at_most_two_parameters(
    reset_state: Stack, page: Any, card_label: str
) -> None:
    """Amount, an optional repeat count and no more than two other controls."""
    stack = reset_state
    player = register(stack, "Две настройки")
    participant_login(page, stack, player["email"])
    code = CODES[card_label]

    choose_option(page, "builder_card", card_label)
    assert (
        page.locator(
            f'[data-testid="builder-operation-icon"][data-operation="{code}"] svg'
        ).count()
        == 1
    )
    exposed = marker(page, "builder-params")
    assert exposed == EXPECTED_VISIBLE_PARAMS[code], card_label
    assert len(exposed.split(",")) <= 2

    assert widget(page, f"builder_{code}_amount").count() == 1
    assert widget(page, f"builder_{code}_channel").count() == 1
    # Everything the round pins has no control at all.
    for hidden in ("ctx_has_documents", "ctx_velocity", "detail_income_basis"):
        assert widget(page, f"builder_{code}_{hidden}").count() == 0, hidden

    shown_frequency = widget(page, f"builder_{code}_frequency").count()
    assert shown_frequency == (
        1 if code in {"cash_deposit", "card_transfer", "cash_withdrawal"} else 0
    )


def test_builder_uses_bounded_fields_in_separate_icon_labeled_rows(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Компактная форма")
    participant_login(page, stack, player["email"])
    choose_option(page, "builder_card", "Внести наличные")

    icon = page.locator(
        '[data-testid="builder-operation-icon"][data-operation="cash_deposit"]'
    )
    assert icon.count() == 1
    assert icon.locator("svg").count() == 1
    assert icon.evaluate("element => getComputedStyle(element).backgroundColor") == (
        "rgb(19, 131, 111)"
    )
    icon_box = icon.bounding_box() or {}
    assert icon_box["width"] == 32
    assert icon_box["height"] == 32

    labels = page.locator(".aml-form-label").all_text_contents()
    assert labels == ["Сумма, ₽", "Повторов", "Канал", "Источник наличных"]
    assert not any("от " in label or "до " in label for label in labels)

    amount = widget(page, "builder_cash_deposit_amount").locator("input").first
    frequency = widget(page, "builder_cash_deposit_frequency").locator("input").first
    assert float(amount.get_attribute("min") or 0) == 5000
    assert float(amount.get_attribute("max") or 0) == 150000
    assert float(frequency.get_attribute("min") or 0) == 1
    assert float(frequency.get_attribute("max") or 0) == 3

    row_keys = [
        "builder_cash_deposit_amount",
        "builder_cash_deposit_frequency",
        "builder_cash_deposit_channel",
        "builder_cash_deposit_detail_funds_source",
    ]
    tops = [(widget(page, key).bounding_box() or {})["y"] for key in row_keys]
    assert tops == sorted(tops)
    assert len(set(tops)) == len(tops)

    gaps = page.evaluate(
        """() => {
            const icon = document.querySelector('[data-testid="builder-operation-icon"]');
            let operationCard = icon;
            while (operationCard) {
                const style = getComputedStyle(operationCard);
                const rect = operationCard.getBoundingClientRect();
                if (Number(style.borderTopWidth.replace('px', '')) > 0
                        && rect.width > 250) break;
                operationCard = operationCard.parentElement;
            }
            const firstLabel = document.querySelector('.aml-form-label');
            const impact = document.querySelector('[data-testid="candidate-impact"]');
            const button = document.querySelector('.st-key-add_step');
            const operationSelect = document.querySelector(
                '.st-key-builder_card [data-testid="stSelectbox"]'
            );
            const iconRect = icon.getBoundingClientRect();
            const selectRect = operationSelect.getBoundingClientRect();
            return {
                cardToFields: firstLabel.getBoundingClientRect().top
                    - operationCard.getBoundingClientRect().bottom,
                impactToButton: button.getBoundingClientRect().top
                    - impact.getBoundingClientRect().bottom,
                iconCenterDelta: Math.abs(
                    iconRect.top + iconRect.height / 2
                    - selectRect.top - selectRect.height / 2
                ),
                iconToSelect: selectRect.left - iconRect.right,
            };
        }"""
    )
    assert 0 < gaps["cardToFields"] < 45
    assert 6 <= gaps["impactToButton"] <= 16
    assert gaps["iconCenterDelta"] <= 1
    assert 8 <= gaps["iconToSelect"] <= 40


def test_hidden_parameters_are_stored_and_survive_a_reload(
    reset_state: Stack, page: Any
) -> None:
    """Hiding a parameter removes its control, not the value behind it."""
    stack = reset_state
    player = register(stack, "Скрытые параметры")
    participant_login(page, stack, player["email"])
    add_step(page, "Получить зарплату", "Банковское зачисление", 120000, None, "salary")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")

    stored = db_query(
        "SELECT s.steps FROM scenarios s JOIN users u ON u.id = s.participant_id "
        "WHERE u.email = %s",
        (player["email"],),
    )[0][0]
    step = stored[0]
    # The visible parameters carry what the participant chose...
    assert step["context"]["channel"] == "bank"
    assert step["context"]["time_of_day"] == "day"
    # ...and the ones the round hides are still written down in full.
    assert step["context"]["has_documents"] is True
    assert step["action_details"]["employer_profile"] == "verified_employer"
    assert step["action_details"]["income_basis"] == "payroll_registry"

    page.reload(wait_until="domcontentloaded")
    expect_marker(page, "auth-state", "authenticated", timeout=60_000)
    expect_marker(page, "chain-length", "1")
    expect_marker(page, "resources-valid", "true")

    # Re-saving an unchanged chain is a no-op, not a new revision.
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")
    assert db_query(
        "SELECT count(*) FROM scenario_versions v JOIN scenarios s ON s.id = v.scenario_id "
        "JOIN users u ON u.id = s.participant_id WHERE u.email = %s",
        (player["email"],),
    ) == [(1,)]


# --------------------------------------------------------------------------
# Chain editing
# --------------------------------------------------------------------------


def test_build_save_and_restore_a_draft_across_logout(reset_state: Stack, page: Any) -> None:
    stack = reset_state
    player = register(stack, "Черновик")
    participant_login(page, stack, player["email"])

    expect_marker(page, "resource-available-steps", "8")
    labels = page.locator('[data-testid="stMetricLabel"]').all_text_contents()
    assert {"Баланс", "Энергия", "Время", "Доступных шагов"} <= set(labels)
    assert "Доверие" not in labels
    assert "Свободных слотов" not in labels
    config = stack.request("GET", "/api/v1/rounds/current")["game_config"]
    initial_energy = config["resources"]["initial_energy"]
    initial_time = config["resources"]["initial_time"]
    assert page.locator('[data-testid="stMetricValue"]').all_text_contents() == [
        marker(page, "resource-balance"),
        f"{initial_energy} из {initial_energy}",
        f"{initial_time} из {initial_time}",
        "8 из 8",
    ]
    assert page.locator('[data-testid="no-violations"]').count() == 0

    build_valid_chain(page)
    expect_marker(page, "resource-available-steps", "5")
    assert page.locator('[data-testid="stMetricValue"]').all_text_contents() == [
        marker(page, "resource-balance"),
        f"{marker(page, 'resource-energy')} из {initial_energy}",
        f"{marker(page, 'resource-time')} из {initial_time}",
        "5 из 8",
    ]
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
    expect_marker(page, "resource-available-steps", "5")
    assert (
        "доверие"
        not in (page.locator('[data-testid="stMain"]').text_content() or "").lower()
    )


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
    expect_step_order(page, [ids[0], ids[2], ids[1]])
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "2")
    reordered = stored_steps()
    assert [step["step_id"] for step in reordered] == [ids[0], ids[2], ids[1]]

    # Duplicate: a new identity, same content.
    click_button(page, f"copy_{ids[0]}")
    expect_marker(page, "chain-length", "4")
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
    expect_marker(page, "chain-length", "3")
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

    page.locator("summary").filter(has_text="Нарушения правил:").click()
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

    # The chain is kept: a business violation is stored, not thrown away.
    step_id = steps[0][0][0]["step_id"]
    assert page.locator(f'[data-testid="step-card-{step_id}"]').count() == 1
    assert page.locator(f'[data-testid="step-impact-{step_id}"]').count() == 1


def test_fixing_a_violation_enables_submit_and_completes_the_round(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Исправление")
    participant_login(page, stack, player["email"])

    # A chain that is structurally fine but breaks the cash quota.
    add_step(page, "Получить зарплату", "Банковское зачисление", 150000, None, "salary")
    add_step(page, "Внести наличные", "Банкомат", 100000, 1, "cash_deposit")
    add_step(page, "Перевести по карте", "Мобильное приложение", 100000, 1, "card_transfer")
    add_step(page, "Снять наличные", "Банкомат", 60000, 1, "cash_withdrawal")
    click_button(page, "save_draft")
    expect_marker(page, "resources-valid", "false")
    page.locator("summary").filter(has_text="Нарушения правил:").click()
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
    expect_marker(page, "chain-length", "3")
    add_step(page, "Снять наличные", "Банкомат", 50000, 1, "cash_withdrawal")
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


def test_live_warnings_and_step_edits_only_rerun_the_workspace(
    reset_state: Stack, page: Any
) -> None:
    """Observe Streamlit's wire messages, not just an unchanged-looking page."""
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

    runs: list[list[str]] = []

    def record_run(payload: Any) -> None:
        if not isinstance(payload, bytes):
            return
        message = ForwardMsg()
        message.ParseFromString(payload)
        if message.HasField("new_session"):
            runs.append(list(message.new_session.fragment_ids_this_run))

    page.on("websocket", lambda socket: socket.on("framereceived", record_run))
    stack = reset_state
    player = register(stack, "Локальные предупреждения")
    participant_login(page, stack, player["email"])
    # Wait for the whole initial render before measuring subsequent interactions.
    page.get_by_text("История появится после первого сохранения черновика.").wait_for()
    runs.clear()

    choose_option(page, "builder_card", "Перевести по карте")
    fill_number(page, "builder_card_transfer_amount", 400000)
    warning = page.locator("summary").filter(has_text="Операция нарушит правила:")
    warning.wait_for(state="visible")
    assert warning.locator("..").get_attribute("open") is None
    expect_marker(page, "chain-length", "0")
    fill_number(page, "builder_card_transfer_amount", 100000)
    warning.wait_for(state="detached")
    click_button(page, "add_step")
    expect_marker(page, "chain-length", "1")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "1")
    step_id = db_query(
        "SELECT s.steps FROM scenarios s JOIN users u ON u.id = s.participant_id "
        "WHERE u.email = %s",
        (player["email"],),
    )[0][0][0]["step_id"]

    page.locator("summary").filter(has_text="Изменить шаг").click()
    fill_number(page, f"edit_{step_id}_amount", 400000)
    expect_marker(page, "resources-valid", "false")
    expect_marker(page, "draft-synchronized", "false")
    chain_warning = page.locator("summary").filter(has_text="Нарушения правил:")
    chain_warning.wait_for(state="visible")
    assert chain_warning.locator("..").get_attribute("open") is None
    chain_warning.scroll_into_view_if_needed()
    page.screenshot(path=str(ARTIFACTS / "participant-compact-warning.png"), full_page=True)
    fill_number(page, f"edit_{step_id}_amount", 150000)
    expect_marker(page, "resources-valid", "true")
    chain_warning.wait_for(state="detached")
    expect_marker(page, "objective-reached", "true")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "2")
    # A context edit must not also mutate the saved scenario's nested dicts.
    choose_option(page, f"edit_{step_id}_channel", "Интернет-банк")
    expect_marker(page, "draft-synchronized", "false")
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "3")
    expect_marker(page, "submit-enabled", "true")
    choose_option(page, "version_select", "Версия 1")
    click_button(page, "restore_version")
    expect_marker(page, "scenario-revision", "4")
    expect_marker(page, "objective-reached", "false")
    assert widget(page, f"edit_{step_id}_amount").locator("input").input_value() == "100000.00"
    assert widget(page, f"edit_{step_id}_channel").locator("input").input_value() == "Мобильное приложение"
    fill_number(page, f"edit_{step_id}_amount", 150000)
    click_button(page, "save_draft")
    expect_marker(page, "scenario-revision", "5")
    page.locator('[data-testid="stMain"]').evaluate("element => element.scrollTop = 0")
    page.screenshot(path=str(ARTIFACTS / "participant-resources.png"), full_page=True)
    click_button(page, "submit_scenario")
    expect_marker(page, "scenario-status", "submitted")
    assert runs, "No Streamlit runs were observed"
    assert all(runs), f"A full-app rerun occurred: {runs}"
    assert page.locator('[data-testid="stException"]').count() == 0


def test_submit_is_blocked_until_the_objective_is_reached(
    reset_state: Stack, page: Any
) -> None:
    stack = reset_state
    player = register(stack, "Цель")
    participant_login(page, stack, player["email"])
    add_step(page, "Перевести по карте", "Мобильное приложение", 50000, 1, "card_transfer")
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

        add_step(page_a, "Получить зарплату", "Банковское зачисление", 100000, None, "salary")
        click_button(page_a, "save_draft")
        expect_marker(page_a, "chain-length", "1")

        add_step(page_b, "Снять наличные", "Банкомат", 30000, 1, "cash_withdrawal")
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
# Responsive and native-theme smoke matrix
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height"),
    [(360, 800), (768, 1024), (1366, 768), (1920, 1080)],
    ids=["mobile", "tablet", "laptop", "desktop"],
)
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_builder_fits_every_viewport_with_the_system_theme(
    reset_state: Stack, browser: Any, width: int, height: int, scheme: str
) -> None:
    stack = reset_state
    player = register(stack, f"Адаптив {scheme}")
    context = browser.new_context(
        viewport={"width": width, "height": height}, color_scheme=scheme
    )
    try:
        page = context.new_page()
        participant_login(page, stack, player["email"])
        add_step(page, "Получить зарплату", "Банковское зачисление", 120000, None, "salary")
        click_button(page, "save_draft")
        expect_marker(page, "scenario-revision", "1")

        assert page.locator('[class*="st-key-theme_toggle"]').count() == 0
        assert not has_horizontal_overflow(page), (width, scheme)
        assert clipped_elements(page) == [], (width, scheme)
        page.screenshot(
            path=str(ARTIFACTS / f"participant-{width}x{height}-{scheme}.png"),
            full_page=True,
        )
    finally:
        context.close()
