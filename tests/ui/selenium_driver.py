"""Selenium helpers for the Streamlit applications.

Every wait is a `WebDriverWait` on a concrete condition — a widget, a marker
value, an enabled control. There is no unconditional `time.sleep`, and no
helper ever accepts "one of several things happened": a wait either observes
the state it was asked for or it raises.

Stale elements are handled by re-resolving the locator inside the wait
predicate (`ignored_exceptions`), which is what makes the helpers survive
Streamlit replacing the whole element tree on every rerun.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

TIMEOUT = 60
FLAKY = (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    NoSuchElementException,
)

#: The latest value of a marker that is not inside a stale render.
FRESH_MARKER = """
const nodes = [...document.querySelectorAll(`[data-testid="${arguments[0]}"]`)]
    .filter(node => !node.closest('[data-stale="true"]'));
return nodes.length ? nodes[nodes.length - 1].textContent.trim() : null;
"""

#: The text of the freshest match for a selector, hidden markers included.
#: `element.text` is empty for `display:none` nodes, which is exactly what the
#: state markers are, so the text always comes from `textContent`.
FRESH_TEXT = """
const nodes = [...document.querySelectorAll(arguments[0])]
    .filter(node => !node.closest('[data-stale="true"]'));
return nodes.length ? nodes[nodes.length - 1].textContent.trim() : null;
"""

VISIBLE_BUTTON = """
return [...document.querySelectorAll('button')]
    .filter(node => !node.closest('[data-stale="true"]'))
    .filter(node => node.offsetParent !== null)
    .filter(node => node.innerText.trim() === arguments[0])
    .length;
"""


def wait(driver: Any, timeout: int = TIMEOUT) -> WebDriverWait:
    return WebDriverWait(driver, timeout, poll_frequency=0.2, ignored_exceptions=FLAKY)


def until(
    driver: Any,
    predicate: Any,
    message: Any,
    timeout: int = TIMEOUT,
) -> Any:
    """`WebDriverWait.until` whose failure message is built *after* the timeout.

    `WebDriverWait` formats its message eagerly, so a diagnostic that reads the
    page would report the state at the start of the wait instead of the state
    that actually failed. A callable message is rendered on failure only.
    """
    try:
        return wait(driver, timeout).until(predicate)
    except TimeoutException:
        raise TimeoutException(message() if callable(message) else message) from None


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------


def marker(driver: Any, testid: str, timeout: int = TIMEOUT) -> str:
    """Value of a state marker once it exists in the current render."""
    value = until(
        driver,
        lambda d: d.execute_script(FRESH_MARKER, testid),
        f"marker {testid!r} never appeared",
        timeout,
    )
    return str(value)


def marker_or_none(driver: Any, testid: str) -> str | None:
    try:
        return driver.execute_script(FRESH_MARKER, testid)
    except JavascriptException:  # pragma: no cover - page still navigating
        return None


def expect_marker(driver: Any, testid: str, expected: str, timeout: int = TIMEOUT) -> None:
    until(
        driver,
        lambda d: d.execute_script(FRESH_MARKER, testid) == expected,
        lambda: (
            f"marker {testid!r} never became {expected!r} "
            f"(last value: {marker_or_none(driver, testid)!r})"
        ),
        timeout,
    )


def wait_idle(driver: Any, timeout: int = TIMEOUT) -> None:
    """Wait until Streamlit has finished the current script run.

    The running indicator alone is not enough: it appears with a delay, so a
    check right after an interaction can pass while the rerun is still on its
    way. Streamlit also marks the previous render `data-stale="true"` for the
    whole rerun, and that flag is set immediately.
    """
    until(
        driver,
        lambda d: not d.find_elements(
            By.CSS_SELECTOR, '[data-testid="stStatusWidget"], [data-stale="true"]'
        ),
        "the app never finished its script run",
        timeout,
    )


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------


def widget(driver: Any, key: str, timeout: int = TIMEOUT) -> Any:
    return wait(driver, timeout).until(
        lambda d: d.find_element(By.CSS_SELECTOR, f".st-key-{key}"),
        f"widget {key!r} never appeared",
    )


def has_widget(driver: Any, key: str) -> bool:
    return bool(driver.find_elements(By.CSS_SELECTOR, f".st-key-{key}"))


def fill(driver: Any, key: str, value: str) -> None:
    """Type into a keyed text input and leave the value committed."""

    def action(d: Any) -> bool:
        field = d.find_element(By.CSS_SELECTOR, f".st-key-{key} input")
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", field)
        field.send_keys(Keys.CONTROL, "a")
        field.send_keys(Keys.DELETE)
        field.send_keys(value)
        return field.get_attribute("value") == value

    wait(driver).until(action, f"could not type into {key!r}")


def field_value(driver: Any, key: str) -> str:
    field = widget(driver, key).find_element(By.CSS_SELECTOR, "input")
    return field.get_attribute("value") or ""


def set_number(driver: Any, key: str, value: Any) -> None:
    """Set a number input and confirm the field kept the value.

    Streamlit commits a number input when it loses focus, and a rerun that
    lands mid-typing throws the keystrokes away, so the value is retyped until
    the field actually shows it.
    """
    target = float(value)

    def committed(field: Any) -> bool:
        raw = (field.get_attribute("value") or "").replace(" ", "").replace(" ", "")
        try:
            return float(raw.replace(",", ".")) == target
        except ValueError:
            return False

    def action(d: Any) -> bool:
        field = d.find_element(By.CSS_SELECTOR, f".st-key-{key} input")
        if committed(field):
            return True
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", field)
        field.send_keys(Keys.CONTROL, "a")
        field.send_keys(str(value))
        field.send_keys(Keys.TAB)
        return False

    until(driver, action, f"could not set {key!r} to {value!r}")
    wait_idle(driver)


def keyed_button(driver: Any, key: str) -> Any:
    """The visible button of a keyed widget.

    A widget with a `help=` tooltip renders a hidden button of its own before
    the real control, so the first match is not always the one to click.
    """
    buttons = [
        node
        for node in driver.find_elements(By.CSS_SELECTOR, f".st-key-{key} button")
        if node.is_displayed()
    ]
    if not buttons:
        raise NoSuchElementException(f"no visible button in {key!r}")
    return buttons[0]


def click(driver: Any, key: str) -> None:
    """Click a keyed button once it is present and enabled."""

    def action(d: Any) -> bool:
        button = keyed_button(d, key)
        if not button.is_enabled():
            return False
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
        button.click()
        return True

    until(driver, action, f"could not click {key!r}")
    wait_idle(driver)


def check(driver: Any, key: str, checked: bool = True) -> None:
    """Bring a keyed checkbox to `checked` and let the rerun settle."""

    def action(d: Any) -> bool:
        box = d.find_element(By.CSS_SELECTOR, f".st-key-{key} input[type='checkbox']")
        if box.is_selected() == checked:
            return True
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)
        box.find_element(By.XPATH, "./ancestor::label[1]").click()
        return False

    until(driver, action, f"could not set the checkbox {key!r} to {checked}")
    wait_idle(driver)


def button_is_disabled(driver: Any, key: str) -> bool:
    widget(driver, key)
    return not keyed_button(driver, key).is_enabled()


def click_text(driver: Any, text: str) -> None:
    """Click the visible button whose label is exactly `text`."""

    def action(d: Any) -> bool:
        buttons = [
            node
            for node in d.find_elements(By.CSS_SELECTOR, "button")
            if node.is_displayed() and node.text.strip() == text
        ]
        if not buttons or not buttons[0].is_enabled():
            return False
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", buttons[0])
        buttons[0].click()
        return True

    wait(driver).until(action, f"could not click the button labelled {text!r}")
    wait_idle(driver)


def click_text_twice(driver: Any, text: str) -> None:
    """Two clicks in immediate succession, without waiting in between.

    Used to prove that a queued second click cannot create a second account or
    a second session.
    """

    def action(d: Any) -> bool:
        buttons = [
            node
            for node in d.find_elements(By.CSS_SELECTOR, "button")
            if node.is_displayed() and node.text.strip() == text
        ]
        if not buttons or not buttons[0].is_enabled():
            return False
        d.execute_script(
            "arguments[0].click(); arguments[0].click();", buttons[0]
        )
        return True

    wait(driver).until(action, f"could not double-click {text!r}")
    wait_idle(driver)


#: Streamlit marks each tab header with this test id.
TAB_SELECTOR = '[data-testid="stTab"], [role="tab"]'


def open_tab(driver: Any, label: str) -> None:
    def action(d: Any) -> bool:
        tabs = [
            node
            for node in d.find_elements(By.CSS_SELECTOR, TAB_SELECTOR)
            if node.text.strip() == label and node.is_displayed()
        ]
        if not tabs:
            return False
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", tabs[0])
        tabs[0].click()
        return True

    wait(driver).until(action, f"tab {label!r} never became clickable")
    wait(driver).until(
        lambda d: any(
            node.get_attribute("aria-selected") == "true"
            for node in d.find_elements(By.CSS_SELECTOR, TAB_SELECTOR)
            if node.text.strip() == label
        ),
        f"tab {label!r} never became the selected one",
    )
    wait_idle(driver)


#: `st.navigation` renders one link per page in the sidebar.
NAV_LINK = '[data-testid="stSidebarNavLink"]'


def open_page(driver: Any, title: str) -> None:
    """Follow a sidebar navigation link and wait for that page to be current."""

    def action(d: Any) -> bool:
        links = [
            node
            for node in d.find_elements(By.CSS_SELECTOR, NAV_LINK)
            if node.text.strip() == title
        ]
        if not links:
            return False
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", links[0])
        links[0].click()
        return True

    until(driver, action, f"navigation link {title!r} never became clickable")
    until(
        driver,
        lambda d: any(
            node.get_attribute("aria-current") == "page"
            for node in d.find_elements(By.CSS_SELECTOR, NAV_LINK)
            if node.text.strip() == title
        ),
        lambda: f"navigation never settled on {title!r} (url: {driver.current_url})",
    )
    wait_idle(driver)


def emulate_viewport(driver: Any, width: int, height: int, mobile: bool = True) -> None:
    """Force a viewport size.

    `set_window_size` cannot be used for phone widths: Chrome clamps its own
    window to a platform minimum (about 500px on Windows), so the page would
    keep a desktop layout. Device-metrics emulation resizes the *viewport*
    itself, which is what the layout responds to.
    """
    driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": mobile,
        },
    )


def reset_viewport(driver: Any) -> None:
    driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})


def viewport_width(driver: Any) -> int:
    return int(driver.execute_script("return window.innerWidth;"))


def choose(driver: Any, key: str, label: str) -> None:
    """Pick a selectbox option by typing it, the way a participant would."""

    def open_and_pick(d: Any) -> bool:
        control = d.find_element(
            By.CSS_SELECTOR, f".st-key-{key} input[role='combobox']"
        )
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", control)
        control.click()
        control.send_keys(Keys.CONTROL, "a")
        control.send_keys(label)
        options = [
            node
            for node in d.find_elements(By.CSS_SELECTOR, '[role="option"]')
            if label in node.text
        ]
        if not options:
            return False
        options[0].click()
        return True

    wait(driver).until(open_and_pick, f"could not select {label!r} in {key!r}")
    wait(driver).until(
        lambda d: label
        in (
            d.find_element(
                By.CSS_SELECTOR, f".st-key-{key} input[role='combobox']"
            ).get_attribute("value")
            or ""
        ),
        f"{key!r} never showed {label!r}",
    )
    wait_idle(driver)


def option_labels(driver: Any, key: str) -> list[str]:
    """Labels a selectbox offers, read from the open listbox."""

    def open_listbox(d: Any) -> bool:
        control = d.find_element(
            By.CSS_SELECTOR, f".st-key-{key} input[role='combobox']"
        )
        d.execute_script("arguments[0].scrollIntoView({block: 'center'});", control)
        control.click()
        return bool(d.find_elements(By.CSS_SELECTOR, '[role="option"]'))

    wait(driver).until(open_listbox, f"listbox of {key!r} never opened")
    labels = [
        node.text.strip()
        for node in driver.find_elements(By.CSS_SELECTOR, '[role="option"]')
    ]
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    return labels


def text_of(driver: Any, css: str) -> str:
    """Text of the freshest node matching `css`, visible or not."""
    value = until(
        driver,
        lambda d: d.execute_script(FRESH_TEXT, css),
        f"{css!r} never carried any text",
    )
    return str(value).strip()


def page_contains(driver: Any, needle: str) -> bool:
    return needle in driver.find_element(By.TAG_NAME, "body").text


# --------------------------------------------------------------------------
# Application flows
# --------------------------------------------------------------------------


def open_app(driver: Any, url: str) -> None:
    """Load an app and wait for its auth state to settle.

    `pending` is the transient state while the cookie component answers; it is
    never an outcome a test should observe.
    """
    driver.get(url)
    until(
        driver,
        lambda d: d.execute_script(FRESH_MARKER, "auth-state")
        not in (None, "", "pending"),
        lambda: (
            f"{url} never settled its auth state "
            f"(last value: {marker_or_none(driver, 'auth-state')!r})"
        ),
    )
    wait_idle(driver)


def login(driver: Any, url: str, email: str, password: str, admin: bool = False) -> None:
    open_app(driver, url)
    if marker(driver, "auth-state") == "authenticated":
        return
    prefix = "admin" if admin else "login"
    if not admin:
        open_tab(driver, "Вход")
    fill(driver, f"{prefix}_email", email)
    fill(driver, f"{prefix}_password", password)
    click_text(driver, "Войти")
    expect_marker(driver, "auth-state", "authenticated")


def try_login(driver: Any, url: str, email: str, password: str, admin: bool = False) -> None:
    """Submit the login form without expecting it to succeed."""
    open_app(driver, url)
    prefix = "admin" if admin else "login"
    if not admin:
        open_tab(driver, "Вход")
    fill(driver, f"{prefix}_email", email)
    fill(driver, f"{prefix}_password", password)
    click_text(driver, "Войти")


def register(
    driver: Any,
    url: str,
    display_name: str,
    email: str,
    password: str,
    confirmation: str | None = None,
) -> None:
    """Fill and submit the registration form. No assertion about the outcome."""
    open_app(driver, url)
    open_tab(driver, "Регистрация")
    fill(driver, "register_name", display_name)
    fill(driver, "register_email", email)
    fill(driver, "register_password", password)
    fill(driver, "register_password_repeat", password if confirmation is None else confirmation)
    click_text(driver, "Зарегистрироваться")


def logout(driver: Any) -> None:
    click(driver, "logout")
    expect_marker(driver, "auth-state", "anonymous")


def current_theme(driver: Any) -> str:
    return marker(driver, "theme-mode")


def toggle_theme(driver: Any, key: str) -> str:
    before = current_theme(driver)
    click(driver, key)
    wait(driver).until(
        lambda d: d.execute_script(FRESH_MARKER, "theme-mode") not in (None, before),
        "the theme never changed",
    )
    return current_theme(driver)


# --------------------------------------------------------------------------
# Failure artefacts
# --------------------------------------------------------------------------


def capture(driver: Any, artifacts: Path, name: str) -> None:
    """Screenshot, page source and browser log of a failed test."""
    artifacts.mkdir(parents=True, exist_ok=True)
    safe = "".join(character if character.isalnum() else "-" for character in name)[:120]
    try:
        driver.save_screenshot(str(artifacts / f"{safe}.png"))
    except Exception:  # noqa: BLE001 - never mask the original failure
        pass
    try:
        (artifacts / f"{safe}.html").write_text(driver.page_source, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        logs = driver.get_log("browser")
        (artifacts / f"{safe}.log.json").write_text(
            json.dumps(logs, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - not every driver exposes logs
        pass


__all__ = [
    "FRESH_MARKER",
    "TIMEOUT",
    "TimeoutException",
    "button_is_disabled",
    "capture",
    "check",
    "choose",
    "click",
    "click_text",
    "click_text_twice",
    "current_theme",
    "emulate_viewport",
    "expect_marker",
    "field_value",
    "fill",
    "has_widget",
    "keyed_button",
    "login",
    "logout",
    "marker",
    "marker_or_none",
    "open_app",
    "open_page",
    "open_tab",
    "option_labels",
    "page_contains",
    "register",
    "reset_viewport",
    "set_number",
    "text_of",
    "toggle_theme",
    "try_login",
    "until",
    "viewport_width",
    "wait",
    "wait_idle",
    "widget",
]
