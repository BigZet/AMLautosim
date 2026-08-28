"""Second browser suite, driven by Selenium instead of Playwright.

It repeats the critical participant journey with an independent automation
stack so a green result is not an artefact of one driver.
"""

from __future__ import annotations

import time
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

from selenium.common.exceptions import (  # noqa: E402
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.common.keys import Keys  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

TIMEOUT = 60

FRESH_MARKERS = """
const nodes = [...document.querySelectorAll(`[data-testid="${arguments[0]}"]`)]
    .filter(node => !node.closest('[data-stale="true"]'));
return nodes.length ? nodes[nodes.length - 1].textContent.trim() : null;
"""


@pytest.fixture(scope="module")
def driver() -> Iterator[Any]:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,1000")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
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
def clear_cookies(driver: Any, reset_state: Stack) -> Iterator[None]:
    driver.get(reset_state.play_url)
    driver.delete_all_cookies()
    yield


def marker(driver: Any, testid: str, timeout: int = TIMEOUT) -> str:
    """Latest value of a non-stale marker."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = driver.execute_script(FRESH_MARKERS, testid)
        if value is not None:
            return str(value)
        time.sleep(0.25)
    raise TimeoutException(f"marker {testid} never appeared")


def wait_marker(driver: Any, testid: str, expected: str, timeout: int = TIMEOUT) -> None:
    end = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < end:
        last = driver.execute_script(FRESH_MARKERS, testid)
        if last == expected:
            return
        time.sleep(0.25)
    raise AssertionError(f"marker {testid} is {last!r}, expected {expected!r}")


def widget(driver: Any, key: str) -> Any:
    return WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.find_element(By.CSS_SELECTOR, f".st-key-{key}")
    )


FLAKY_ERRORS = (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    TimeoutException,
)


def retrying(action: Any, attempts: int = 4, description: str = "action") -> Any:
    """Re-run an interaction whose element was replaced by a Streamlit rerun."""
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return action()
        except FLAKY_ERRORS as error:
            last_error = error
            time.sleep(0.5)
    raise AssertionError(f"{description} failed: {last_error}")


def type_into(driver: Any, key: str, value: str) -> None:
    def action() -> None:
        field = widget(driver, key).find_element(By.CSS_SELECTOR, "input")
        field.clear()
        field.send_keys(value)

    retrying(action, description=f"type into {key}")


def click(driver: Any, key: str) -> None:
    def action() -> None:
        button = WebDriverWait(driver, TIMEOUT).until(
            lambda d: d.find_element(By.CSS_SELECTOR, f".st-key-{key} button")
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        WebDriverWait(driver, TIMEOUT).until(lambda _: button.is_enabled())
        try:
            button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", button)

    retrying(action, description=f"click {key}")


def choose(driver: Any, key: str, label: str) -> None:
    """Select a combobox option by typing it, like a participant would.

    The react-aria listbox re-renders while it filters, so the option is
    re-resolved immediately before the click and stale references are retried.
    """
    last_error: Exception | None = None
    for _ in range(4):
        try:
            control = widget(driver, key).find_element(
                By.CSS_SELECTOR, 'input[role="combobox"]'
            )
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", control
            )
            control.click()
            control.send_keys(Keys.CONTROL, "a")
            control.send_keys(label)
            WebDriverWait(driver, TIMEOUT).until(
                lambda d: any(
                    label in item.text
                    for item in d.find_elements(By.CSS_SELECTOR, '[role="option"]')
                )
            )
            option = next(
                item
                for item in driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
                if label in item.text
            )
            option.click()
            WebDriverWait(driver, TIMEOUT).until(
                lambda d: label
                in d.find_element(
                    By.CSS_SELECTOR, f".st-key-{key} input[role='combobox']"
                ).get_attribute("value")
            )
            return
        except (
            StaleElementReferenceException,
            ElementClickInterceptedException,
            ElementNotInteractableException,
            TimeoutException,
        ) as error:
            last_error = error
            time.sleep(0.5)
    raise AssertionError(f"could not select {label!r} in {key!r}: {last_error}")


def marker_equals(driver: Any, testid: str, expected: str, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if driver.execute_script(FRESH_MARKERS, testid) == expected:
            return True
        time.sleep(0.25)
    return False


def click_until_marker(
    driver: Any, key: str, testid: str, expected: str, attempts: int = 3
) -> None:
    """Click and confirm the effect; a click lost to a rerun is repeated."""
    for _ in range(attempts):
        click(driver, key)
        if marker_equals(driver, testid, expected, timeout=15):
            return
    raise AssertionError(
        f"clicking {key} never made {testid} become {expected!r}"
    )


def set_number(driver: Any, key: str, value: Any) -> None:
    def action() -> None:
        field = widget(driver, key).find_element(By.CSS_SELECTOR, "input")
        field.send_keys(Keys.CONTROL, "a")
        field.send_keys(str(value))
        field.send_keys(Keys.ENTER)

    retrying(action, description=f"set {key}")


def login(driver: Any, url: str, email: str, password: str, admin: bool = False) -> None:
    driver.get(url)
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.execute_script(FRESH_MARKERS, "auth-state") is not None
    )
    if marker(driver, "auth-state") == "authenticated":
        return
    prefix = "admin" if admin else "login"
    type_into(driver, f"{prefix}_email", email)
    type_into(driver, f"{prefix}_password", password)
    def submit() -> None:
        button = WebDriverWait(driver, TIMEOUT).until(
            lambda d: next(
                (
                    item
                    for item in d.find_elements(By.CSS_SELECTOR, "button")
                    if item.text.strip() == "Войти" and item.is_displayed()
                ),
                None,
            )
        )
        button.click()

    retrying(submit, description="submit login")
    wait_marker(driver, "auth-state", "authenticated")


def add_step(
    driver: Any,
    card_label: str,
    code: str,
    channel_label: str,
    amount: float,
    frequency: int = 1,
) -> None:
    before = int(marker(driver, "chain-length"))
    choose(driver, "builder_card", card_label)
    set_number(driver, f"builder_{code}_amount", amount)
    set_number(driver, f"builder_{code}_frequency", frequency)
    choose(driver, f"builder_{code}_channel", channel_label)
    click_until_marker(driver, "add_step", "chain-length", str(before + 1))


def test_selenium_participant_builds_saves_and_submits(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Selenium игрок")
    login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    marker(driver, "chain-length")

    add_step(driver, "Получить зарплату", "salary", "Банковское зачисление", 120000)
    add_step(driver, "Оплатить покупку", "online_purchase", "Интернет-банк", 100000)
    add_step(driver, "Перевести по карте", "card_transfer", "Мобильное приложение", 60000)

    click(driver, "save_draft")
    wait_marker(driver, "scenario-revision", "1")
    wait_marker(driver, "resources-valid", "true")
    wait_marker(driver, "objective-reached", "true")

    rows = db_query(
        "SELECT s.status, s.revision, jsonb_array_length(s.steps) FROM scenarios s "
        "JOIN users u ON u.id = s.participant_id WHERE u.email = %s",
        (player["email"],),
    )
    assert rows == [("draft", 1, 3)]

    click(driver, "submit_scenario")
    wait_marker(driver, "scenario-status", "submitted")
    assert db_query(
        "SELECT s.status FROM scenarios s JOIN users u ON u.id = s.participant_id "
        "WHERE u.email = %s",
        (player["email"],),
    ) == [("submitted",)]


def test_selenium_rejects_a_business_violation_and_recovers(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Selenium нарушение")
    login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    marker(driver, "chain-length")

    add_step(driver, "Перевести по карте", "card_transfer", "Мобильное приложение", 400000)
    click(driver, "save_draft")
    wait_marker(driver, "scenario-revision", "1")
    wait_marker(driver, "resources-valid", "false")

    violation = WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.find_element(
            By.CSS_SELECTOR, '[data-testid="violation-insufficient_balance"]'
        )
    )
    assert "Шаг 1" in violation.text
    assert "Уменьшите сумму" in violation.text
    assert not driver.find_element(
        By.CSS_SELECTOR, ".st-key-submit_scenario button"
    ).is_enabled()

    stored = db_query(
        "SELECT s.steps FROM scenarios s JOIN users u ON u.id = s.participant_id "
        "WHERE u.email = %s",
        (player["email"],),
    )[0][0]
    click(driver, f"delete_{stored[0]['step_id']}")
    add_step(driver, "Получить зарплату", "salary", "Банковское зачисление", 150000)
    add_step(driver, "Оплатить покупку", "online_purchase", "Интернет-банк", 150000)
    click(driver, "save_draft")
    wait_marker(driver, "resources-valid", "true")
    wait_marker(driver, "objective-reached", "true")
    click(driver, "submit_scenario")
    wait_marker(driver, "scenario-status", "submitted")


def test_selenium_channel_selector_matches_the_card_contract(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    player = register(stack, "Selenium каналы")
    login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    marker(driver, "chain-length")

    choose(driver, "builder_card", "Внести наличные")
    assert marker(driver, "builder-channels") == "atm,branch"
    control = widget(driver, "builder_cash_deposit_channel").find_element(
        By.CSS_SELECTOR, 'input[role="combobox"]'
    )
    control.click()
    options = WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, '[role="option"]') or False
    )
    labels = [item.text.strip() for item in options]
    assert labels == ["Банкомат", "Отделение банка"]
    assert "Банковское зачисление" not in labels
    assert "POS-терминал" not in labels


def test_selenium_draft_survives_logout_and_login(reset_state: Stack, driver: Any) -> None:
    stack = reset_state
    player = register(stack, "Selenium черновик")
    login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    marker(driver, "chain-length")
    add_step(driver, "Получить зарплату", "salary", "Банковское зачисление", 100000)
    click(driver, "save_draft")
    wait_marker(driver, "scenario-revision", "1")

    click(driver, "logout")
    wait_marker(driver, "auth-state", "anonymous")
    login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    wait_marker(driver, "chain-length", "1")
    wait_marker(driver, "scenario-revision", "1")


def test_selenium_admin_monitoring_and_scoring(reset_state: Stack, driver: Any) -> None:
    stack = reset_state
    player = register(stack, "Selenium админ")
    login(driver, stack.play_url, player["email"], PARTICIPANT_PASSWORD)
    marker(driver, "chain-length")
    add_step(driver, "Получить зарплату", "salary", "Банковское зачисление", 120000)
    add_step(driver, "Оплатить покупку", "online_purchase", "Интернет-банк", 100000)
    add_step(driver, "Перевести по карте", "card_transfer", "Мобильное приложение", 60000)
    click(driver, "save_draft")
    click(driver, "submit_scenario")
    wait_marker(driver, "scenario-status", "submitted")

    login(driver, stack.admin_url, ADMIN_EMAIL, ADMIN_PASSWORD, admin=True)
    wait_marker(driver, "stat-submitted", "1")
    click(driver, "run_scoring")
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, '[data-testid="flash-success"]')
    )
    assert db_query("SELECT count(*) FROM scoring_results") == [(1,)]

    driver.save_screenshot(str(ARTIFACTS / "selenium-admin-monitoring.png"))
