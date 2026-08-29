"""The workshop journey itself, driven through a real browser.

Where `test_selenium_auth.py` covers getting *into* the applications, this
suite covers what happens afterwards, and it follows the acceptance list of the
task one flow at a time:

* a participant waits until the organiser starts the round;
* resources fall while the chain is being built, before anything is saved;
* several drafts are kept, and an old one can be continued without losing the
  newer ones;
* the administrator sees every version and every parameter of every step,
  including the ones the round hides;
* a submitted version is the one that gets scored;
* stopping the round makes the server refuse further writes;
* restarting creates a new round and keeps the whole history;
* the leaderboard hides a provocative nickname until it is revealed;
* the appearance choice survives navigation in both panels.

Every wait is a `WebDriverWait` on a concrete condition. There is no
`time.sleep`, no "one of several things happened" assertion, and every check
about stored state is made against PostgreSQL.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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

selenium_webdriver = pytest.importorskip("selenium.webdriver")

from tests.ui.selenium_driver import (  # noqa: E402
    capture,
    check,
    choose,
    click,
    click_text,
    click_text_twice,
    current_theme,
    expect_marker,
    fill,
    has_widget,
    logout,
    marker,
    open_app,
    open_page,
    open_tab,
    page_contains,
    set_number,
    text_of,
    toggle_theme,
)
from tests.ui.selenium_driver import login as ui_login  # noqa: E402

PROVOCATIVE_NICKNAME = "ОтмываюМиллионы666"

#: Titles as the builder shows them, next to the widget-key prefix of the card.
SALARY = ("salary", "Получить зарплату")
CARD_TRANSFER = ("card_transfer", "Перевести по карте")
CASH_WITHDRAWAL = ("cash_withdrawal", "Снять наличные")


@pytest.fixture(scope="module")
def driver() -> Iterator[Any]:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    try:
        instance = webdriver.Chrome(options=options)
    except Exception as exc:  # pragma: no cover - environment without Chrome
        pytest.skip(f"Chrome/chromedriver unavailable for Selenium: {exc}")
    instance.set_page_load_timeout(120)
    try:
        yield instance
    finally:
        instance.quit()


@pytest.fixture(autouse=True)
def isolated_browser(driver: Any, request) -> Iterator[None]:
    """A clean browser session per test, and artefacts when one fails."""
    stack = request.getfixturevalue(
        "draft_state" if "draft_state" in request.fixturenames else "reset_state"
    )
    driver.get(stack.play_url)
    driver.delete_all_cookies()
    driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    try:
        yield
    finally:
        if getattr(request.node, "_selenium_failed", False):
            capture(driver, ARTIFACTS, request.node.name)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def api_call(
    stack: Stack,
    method: str,
    path: str,
    body: dict | None = None,
    session_id: str | None = None,
) -> tuple[int, str]:
    """One raw API call that reports its status instead of raising."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{stack.api_url}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if session_id:
        request.add_header("X-Session-ID", session_id)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def api_session(stack: Stack, email: str) -> str:
    """A server session for a participant, used only for negative API checks."""
    payload = stack.request(
        "POST",
        "/api/v1/auth/login",
        {"email": email, "password": PARTICIPANT_PASSWORD, "audience": "play"},
    )
    return payload["session_id"]


def current_round_id(stack: Stack) -> int:
    return int(db_query("SELECT max(id) FROM rounds")[0][0])


def add_step(
    driver: Any,
    card: tuple[str, str],
    amount: int,
    channel_label: str,
    frequency: int | None = None,
    parameter: tuple[str, str] | None = None,
) -> None:
    """Configure one operation in the builder and put it into the chain."""
    code, title = card
    before = int(marker(driver, "chain-length"))
    choose(driver, "builder_card", title)
    set_number(driver, f"builder_{code}_amount", amount)
    if frequency is not None:
        set_number(driver, f"builder_{code}_frequency", frequency)
    choose(driver, f"builder_{code}_channel", channel_label)
    if parameter is not None:
        suffix, label = parameter
        choose(driver, f"builder_{code}_{suffix}", label)
    click(driver, "add_step")
    expect_marker(driver, "chain-length", str(before + 1))


def build_goal_chain(driver: Any) -> None:
    """Salary in, transfer out, cash out: exactly the 150 000 target outflow."""
    add_step(driver, SALARY, 120000, "Банковское зачисление")
    add_step(driver, CARD_TRANSFER, 100000, "Мобильное приложение", frequency=1)
    add_step(driver, CASH_WITHDRAWAL, 50000, "Банкомат", frequency=1)
    expect_marker(driver, "objective-reached", "true")
    expect_marker(driver, "resources-valid", "true")


def save_draft(driver: Any, label: str, expected_revision: int) -> None:
    fill(driver, "draft_label", label)
    click(driver, "save_draft")
    expect_marker(driver, "scenario-revision", str(expected_revision))


def versions_of(email: str) -> list[tuple[int, int]]:
    """(revision, number of steps) of everything the participant ever saved."""
    return [
        (int(revision), int(steps))
        for revision, steps in db_query(
            "SELECT v.revision, jsonb_array_length(v.steps) "
            "FROM scenario_versions v "
            "JOIN scenarios s ON s.id = v.scenario_id "
            "JOIN users u ON u.id = s.participant_id "
            "WHERE u.email = %s ORDER BY v.revision",
            (email,),
        )
    ]


def open_admin_round_page(driver: Any, stack: Stack) -> None:
    ui_login(driver, stack.admin_url, ADMIN_EMAIL, ADMIN_PASSWORD, admin=True)
    open_page(driver, "Раунд и конфигурация")
    open_tab(driver, "Управление раундом")


# --------------------------------------------------------------------------
# 1. Nothing can be played before the organiser starts the round
# --------------------------------------------------------------------------


def test_the_participant_waits_until_the_organiser_starts_the_round(
    draft_state: Stack, driver: Any
) -> None:
    stack = draft_state
    player = register(stack, "Ожидающий")
    round_id = current_round_id(stack)

    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    expect_marker(driver, "round-status", "draft")
    assert page_contains(driver, "Ожидание раунда")
    assert not has_widget(driver, "add_step"), "the builder must stay closed"
    assert not has_widget(driver, "save_draft")

    # The waiting screen is not the only guard: the server refuses the write.
    status, body = api_call(
        stack,
        "PUT",
        f"/api/v1/rounds/{round_id}/scenario",
        {
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
            "steps": [],
        },
        api_session(stack, player["email"]),
    )
    assert status == 409, body
    assert "не запущен" in body

    open_admin_round_page(driver, stack)
    expect_marker(driver, "round-status", "draft")
    click(driver, "start_round")
    expect_marker(driver, "round-status", "active")
    assert db_query("SELECT status FROM rounds WHERE id = %s", (round_id,)) == [
        ("active",)
    ]

    open_app(driver, stack.play_url)
    expect_marker(driver, "round-status", "active")
    expect_marker(driver, "chain-length", "0")
    assert has_widget(driver, "add_step"), "the builder must open once the round runs"


# --------------------------------------------------------------------------
# 2. Resources answer every edit, before anything is saved
# --------------------------------------------------------------------------


def test_the_resources_react_to_every_edit_before_the_draft_is_saved(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Живые ресурсы")
    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    expect_marker(driver, "chain-length", "0")

    balance = marker(driver, "resource-balance")
    energy = int(marker(driver, "resource-energy"))
    time_left = int(marker(driver, "resource-time"))
    slots = int(marker(driver, "resource-slots"))
    assert marker(driver, "objective-progress") == "0.00/150000.00"

    add_step(driver, CASH_WITHDRAWAL, 50000, "Банкомат", frequency=1)

    assert marker(driver, "resource-balance") != balance
    assert int(marker(driver, "resource-energy")) < energy
    assert int(marker(driver, "resource-time")) < time_left
    assert int(marker(driver, "resource-slots")) == slots - 1
    assert marker(driver, "objective-progress") == "50000.00/150000.00"

    # Nothing has been saved: the numbers came from the round's own config.
    assert marker(driver, "scenario-revision") == "0"
    assert db_query("SELECT count(*) FROM scenarios") == [(0,)]

    # The next candidate is priced before it is added.
    choose(driver, "builder_card", CARD_TRANSFER[1])
    set_number(driver, f"builder_{CARD_TRANSFER[0]}_amount", 30000)
    assert "баланс" in text_of(driver, '[data-testid="candidate-impact"]')

    click_text(driver, "Удалить")
    expect_marker(driver, "chain-length", "0")
    assert marker(driver, "resource-balance") == balance
    assert int(marker(driver, "resource-energy")) == energy
    assert int(marker(driver, "resource-slots")) == slots
    assert marker(driver, "objective-progress") == "0.00/150000.00"


# --------------------------------------------------------------------------
# 3. Draft history: several versions, and a way back to an old one
# --------------------------------------------------------------------------


def test_saved_versions_accumulate_and_an_old_one_can_be_continued(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Историк")
    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)

    add_step(driver, SALARY, 120000, "Банковское зачисление")
    save_draft(driver, "Только зарплата", expected_revision=1)
    expect_marker(driver, "version-count", "1")

    add_step(driver, CARD_TRANSFER, 100000, "Мобильное приложение", frequency=1)
    save_draft(driver, "Зарплата и перевод", expected_revision=2)
    expect_marker(driver, "version-count", "2")
    expect_marker(driver, "chain-length", "2")

    choose(driver, "version_select", "Версия 1")
    expect_marker(driver, "selected-version", "1")
    click(driver, "restore_version")

    # Restoring is a new revision, not a rollback: version 2 is still there.
    expect_marker(driver, "scenario-revision", "3")
    expect_marker(driver, "version-count", "3")
    expect_marker(driver, "chain-length", "1")
    assert versions_of(player["email"]) == [(1, 1), (2, 2), (3, 1)]
    assert db_query(
        "SELECT v.revision FROM scenario_versions v "
        "JOIN scenarios s ON s.current_version_id = v.id "
        "JOIN users u ON u.id = s.participant_id WHERE u.email = %s",
        (player["email"],),
    ) == [(3,)]


# --------------------------------------------------------------------------
# 4. The administrator sees every version and every parameter of a step
# --------------------------------------------------------------------------


def test_the_admin_inspector_shows_every_version_and_every_parameter(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Ночной игрок")
    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)

    add_step(
        driver,
        SALARY,
        120000,
        "Банковское зачисление",
        parameter=("ctx_time_of_day", "Ночь"),
    )
    save_draft(driver, "Ночная зарплата", expected_revision=1)
    add_step(driver, CARD_TRANSFER, 100000, "Мобильное приложение", frequency=1)
    save_draft(driver, "С переводом", expected_revision=2)

    ui_login(driver, stack.admin_url, ADMIN_EMAIL, ADMIN_PASSWORD, admin=True)
    open_page(driver, "Участники")
    expect_marker(driver, "participant-count", "1")
    open_tab(driver, "Версии черновиков")
    expect_marker(driver, "versions-count", "2")

    choose(driver, "admin_version_select", "Версия 1")
    expect_marker(driver, "admin-version-revision", "1")
    expect_marker(driver, "admin-version-steps", "1")

    parameters = text_of(driver, '[data-testid^="step-params-"]')
    # The visible parameter, with the value the participant actually chose.
    assert "Канал" in parameters
    assert "Банковское зачисление" in parameters and "(bank)" in parameters
    assert "Время операции" in parameters and "Ночь" in parameters
    assert "(night)" in parameters
    # And the parameters this round hides, defaults and booleans included.
    assert "Есть подтверждающие документы" in parameters
    assert "Да" in parameters and "(True)" in parameters
    assert "Плательщик" in parameters and "Проверенный работодатель" in parameters
    assert "Основание дохода" in parameters and "Зарплатный реестр" in parameters
    assert page_contains(driver, "Ресурсы до")
    assert page_contains(driver, "Ресурсы после")

    choose(driver, "admin_version_select", "Версия 2")
    expect_marker(driver, "admin-version-revision", "2")
    expect_marker(driver, "admin-version-steps", "2")


# --------------------------------------------------------------------------
# 5. Submitting freezes one version, and that version is what gets scored
# --------------------------------------------------------------------------


def test_a_submitted_version_is_the_one_that_gets_scored(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, PROVOCATIVE_NICKNAME)
    round_id = current_round_id(stack)
    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)

    build_goal_chain(driver)
    save_draft(driver, "Финальная", expected_revision=1)
    expect_marker(driver, "submit-enabled", "true")
    click(driver, "submit_scenario")
    expect_marker(driver, "scenario-status", "submitted")

    assert db_query(
        "SELECT s.status, v.revision FROM scenarios s "
        "JOIN scenario_versions v ON v.id = s.submitted_version_id "
        "JOIN users u ON u.id = s.participant_id WHERE u.email = %s",
        (player["email"],),
    ) == [("submitted", 1)]

    # A second participant, who only saves a draft, is excluded from scoring
    # and is the one who must never see the nickname of the first one.
    logout(driver)
    watcher = register(stack, "Зритель")
    ui_login(driver, stack.play_url, watcher["email"], PARTICIPANT_PASSWORD)
    add_step(driver, SALARY, 10000, "Банковское зачисление")
    save_draft(driver, "Черновик зрителя", expected_revision=1)
    logout(driver)

    ui_login(driver, stack.admin_url, ADMIN_EMAIL, ADMIN_PASSWORD, admin=True)
    expect_marker(driver, "stat-submitted", "1")
    expect_marker(driver, "stat-drafts", "1")
    expect_marker(driver, "stat-versions", "2")
    expect_marker(driver, "scoring-can-score", "true")
    assert page_contains(driver, "Черновики без отправки будут исключены: 1")
    check(driver, "confirm_scoring")
    click(driver, "run_scoring")
    assert "Скоринг завершен" in text_of(driver, '[data-testid="flash-success"]')
    assert db_query("SELECT count(*) FROM scoring_results") == [(1,)]

    # 12. The board hides the nickname until somebody asks for it.
    status, body = api_call(stack, "GET", f"/api/v1/rounds/{round_id}/leaderboard")
    assert status == 200
    assert PROVOCATIVE_NICKNAME not in body, "the public API leaked the nickname"
    assert "Игрок #1" in body

    ui_login(driver, stack.play_url, watcher["email"], PARTICIPANT_PASSWORD)
    open_page(driver, "Лидерборд")
    expect_marker(driver, "leaderboard-rows", "1")
    expect_marker(driver, "names-revealed", "false")
    assert PROVOCATIVE_NICKNAME not in driver.page_source, (
        "the nickname reached the browser before it was revealed"
    )
    assert "Игрок #1" in text_of(driver, '[data-testid="leaderboard-table"]')

    click(driver, "reveal_names")
    expect_marker(driver, "names-revealed", "true")
    assert PROVOCATIVE_NICKNAME in text_of(driver, '[data-testid="leaderboard-table"]')

    click(driver, "hide_names")
    expect_marker(driver, "names-revealed", "false")
    assert PROVOCATIVE_NICKNAME not in driver.page_source


# --------------------------------------------------------------------------
# 6. A stopped round is closed by the server, not only by the interface
# --------------------------------------------------------------------------


def test_stopping_the_round_blocks_every_further_write(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Остановленный")
    round_id = current_round_id(stack)
    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    add_step(driver, SALARY, 120000, "Банковское зачисление")
    save_draft(driver, "До остановки", expected_revision=1)

    open_admin_round_page(driver, stack)
    check(driver, "confirm_stop")
    click(driver, "stop_round")
    expect_marker(driver, "round-status", "stopped")

    status, body = api_call(
        stack,
        "PUT",
        f"/api/v1/rounds/{round_id}/scenario",
        {
            "expected_revision": 1,
            "client_mutation_id": str(uuid.uuid4()),
            "steps": [],
        },
        api_session(stack, player["email"]),
    )
    assert status == 409, body
    assert "остановлен" in body

    open_app(driver, stack.play_url)
    expect_marker(driver, "round-status", "stopped")
    assert not has_widget(driver, "save_draft")
    assert not has_widget(driver, "add_step")
    # Nothing was destroyed by stopping the round.
    assert versions_of(player["email"]) == [(1, 1)]


# --------------------------------------------------------------------------
# 7. Restarting keeps every scenario, draft and audit record
# --------------------------------------------------------------------------


def test_restarting_creates_a_new_round_and_keeps_the_history(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Переживший перезапуск")
    original_id = current_round_id(stack)
    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    add_step(driver, SALARY, 120000, "Банковское зачисление")
    save_draft(driver, "До перезапуска", expected_revision=1)

    open_admin_round_page(driver, stack)
    choose(driver, "setup_round_select", f"#{original_id}")
    expect_marker(driver, "round-id", str(original_id))
    check(driver, "confirm_restart")
    # Two clicks in a row must still produce exactly one replacement round.
    click_text_twice(driver, "Перезапустить раунд")
    expect_marker(driver, "round-count", "2")

    rounds = db_query(
        "SELECT id, status, restarted_from_round_id FROM rounds ORDER BY id"
    )
    assert len(rounds) == 2, rounds
    assert rounds[0] == (original_id, "stopped", None)
    replacement_id, replacement_status, restarted_from = rounds[1]
    assert replacement_status == "draft"
    assert restarted_from == original_id

    # The old round keeps its scenario, its versions and its audit trail.
    assert versions_of(player["email"]) == [(1, 1)]
    assert db_query(
        "SELECT count(*) FROM scenarios WHERE round_id = %s", (original_id,)
    ) == [(1,)]
    assert db_query(
        "SELECT count(*) FROM audit_events WHERE event_type = 'round_restarted'"
    ) == [(1,)]

    assert db_query("SELECT count(*) FROM rounds") == [(2,)]

    # `st.rerun()` rebuilds the tab strip, so the management tab is re-opened.
    open_tab(driver, "Управление раундом")
    choose(driver, "setup_round_select", f"#{replacement_id}")
    expect_marker(driver, "round-id", str(replacement_id))
    expect_marker(driver, "round-status", "draft")
    click(driver, "start_round")
    expect_marker(driver, "round-status", "active")
    assert db_query("SELECT status FROM rounds ORDER BY id") == [
        ("stopped",),
        ("active",),
    ]


# --------------------------------------------------------------------------
# 8. The appearance choice survives navigation in both panels
# --------------------------------------------------------------------------


def test_the_theme_choice_survives_navigation_in_both_panels(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Тёмный режим")

    ui_login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    assert current_theme(driver) == "dark", "dark is the default appearance"
    assert toggle_theme(driver, "theme_toggle_app") == "light"
    open_page(driver, "Лидерборд")
    assert current_theme(driver) == "light"
    open_page(driver, "Конструктор")
    assert current_theme(driver) == "light"
    driver.refresh()
    expect_marker(driver, "theme-mode", "light")

    # The choice belongs to the browser, so the admin panel opens in it too.
    ui_login(driver, stack.admin_url, ADMIN_EMAIL, ADMIN_PASSWORD, admin=True)
    assert current_theme(driver) == "light"
    assert toggle_theme(driver, "theme_toggle_app") == "dark"
    open_page(driver, "Участники")
    assert current_theme(driver) == "dark"
    open_page(driver, "Аудит")
    assert current_theme(driver) == "dark"
