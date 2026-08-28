"""Playwright helpers for driving the Streamlit apps.

Every helper waits for a concrete DOM state — a widget, an option, a marker
value — instead of sleeping. `marker(...)` reads the hidden `data-testid`
anchors the apps render for exactly this purpose.
"""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

DEFAULT_TIMEOUT = 30_000


def widget(page: Page, key: str) -> Locator:
    """Container of a Streamlit widget declared with `key=`."""
    return page.locator(f".st-key-{key}")


def marker_locator(page: Page, testid: str) -> Locator:
    return page.locator(
        f'[data-testid="stElementContainer"]:not([data-stale="true"]) '
        f'[data-testid="{testid}"]'
    )


#: Streamlit keeps the previous render in the DOM until the new one lands and
#: marks it `data-stale="true"`, so a marker is only trustworthy when it is read
#: from a fresh container.
_FRESH_MARKERS = """(id) => [...document.querySelectorAll(`[data-testid="${id}"]`)]
    .filter(node => !node.closest('[data-stale="true"]'))
    .map(node => node.textContent.trim())"""


def marker(page: Page, testid: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Value of a state marker from the current, non-stale render.

    The wait and the read are one call so a rerun between them cannot make the
    value disappear.
    """
    handle = page.wait_for_function(
        f"(id) => {{ const values = ({_FRESH_MARKERS})(id);"
        " return values.length ? values[values.length - 1] : null; }",
        arg=testid,
        timeout=timeout,
    )
    return str(handle.json_value())


def expect_marker(
    page: Page, testid: str, value: str, timeout: int = DEFAULT_TIMEOUT
) -> None:
    page.wait_for_function(
        f"([id, expected]) => {{ const values = ({_FRESH_MARKERS})(id);"
        " return values.length > 0 && values[values.length - 1] === expected; }",
        arg=[testid, value],
        timeout=timeout,
    )


def expect_marker_at_least(
    page: Page, testid: str, minimum: int, timeout: int = DEFAULT_TIMEOUT
) -> None:
    """Poll a numeric marker until it reaches `minimum`.

    Streamlit replaces elements one by one during a rerun, so a single read can
    catch a value from the previous run.
    """
    page.wait_for_function(
        f"([id, least]) => {{ const values = ({_FRESH_MARKERS})(id);"
        " return values.length > 0 && Number(values[values.length - 1]) >= least; }",
        arg=[testid, minimum],
        timeout=timeout,
    )


def wait_idle(page: Page, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Wait until Streamlit has finished the current script run."""
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')",
        timeout=timeout,
    )


def fill_text(page: Page, key: str, value: str) -> None:
    field = widget(page, key).locator("input").first
    field.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    field.fill(value)


def fill_number(page: Page, key: str, value: Any) -> None:
    field = widget(page, key).locator("input").first
    field.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    field.fill(str(value))
    field.press("Enter")
    wait_idle(page)


def click_button(page: Page, key: str) -> None:
    button = widget(page, key).locator("button").first
    button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    expect(button).to_be_enabled(timeout=DEFAULT_TIMEOUT)
    button.click()
    wait_idle(page)


def button_is_disabled(page: Page, key: str) -> bool:
    button = widget(page, key).locator("button").first
    button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return button.is_disabled()


def _combobox(page: Page, key: str) -> Locator:
    """Streamlit renders selectboxes as a react-aria combobox input."""
    control = widget(page, key).locator('input[role="combobox"]').first
    control.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return control


def _open_listbox(page: Page, key: str) -> Locator:
    _combobox(page, key).click()
    listbox = page.locator('[role="listbox"]').last
    listbox.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return listbox


def select_options(page: Page, key: str) -> list[str]:
    """Open a selectbox, read the offered labels and close it again."""
    listbox = _open_listbox(page, key)
    labels = [
        (text or "").strip()
        for text in listbox.locator('[role="option"]').all_text_contents()
    ]
    page.keyboard.press("Escape")
    return labels


def choose_option(page: Page, key: str, label: str) -> None:
    """Pick an option by typing it: works at every viewport width.

    Real key events are used because the react-aria combobox only opens and
    filters its listbox in response to them. Narrow viewports occasionally
    swallow the first interaction, so the attempt is repeated once.
    """
    option = page.locator('[role="option"]').filter(has_text=label).first
    last_error: Exception | None = None
    for attempt in range(3):
        control = _combobox(page, key)
        try:
            control.scroll_into_view_if_needed()
            control.click()
            control.press("ControlOrMeta+a")
            control.press_sequentially(label, delay=15)
            if option.count() == 0:
                control.press("ArrowDown")
            option.wait_for(state="attached", timeout=5_000 if attempt < 2 else DEFAULT_TIMEOUT)
            option.click()
            break
        except PlaywrightTimeoutError as error:  # narrow viewport hiccup
            last_error = error
            page.keyboard.press("Escape")
    else:  # pragma: no cover - only reached when every attempt failed
        raise AssertionError(f"could not select {label!r} in {key!r}") from last_error
    wait_idle(page)
    # The rendered value may carry a suffix such as " · Поступление".
    expect(_combobox(page, key)).to_have_value(
        re.compile(re.escape(label)), timeout=DEFAULT_TIMEOUT
    )


def selected_option(page: Page, key: str) -> str:
    return (_combobox(page, key).input_value() or "").strip()


def open_app(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.locator('[data-testid="auth-state"]').first.wait_for(
        state="attached", timeout=60_000
    )


def login(page: Page, url: str, email: str, password: str, admin: bool = False) -> None:
    open_app(page, url)
    if marker(page, "auth-state") == "authenticated":
        return
    prefix = "admin" if admin else "login"
    fill_text(page, f"{prefix}_email", email)
    fill_text(page, f"{prefix}_password", password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect_marker(page, "auth-state", "authenticated", timeout=60_000)


def logout(page: Page) -> None:
    click_button(page, "logout")
    expect_marker(page, "auth-state", "anonymous", timeout=60_000)


def register(page: Page, url: str, email: str, display_name: str, password: str) -> None:
    open_app(page, url)
    page.get_by_role("tab", name="Регистрация").click()
    fill_text(page, "register_name", display_name)
    fill_text(page, "register_email", email)
    fill_text(page, "register_password", password)
    page.get_by_role("button", name="Зарегистрироваться", exact=True).click()
    page.locator('[data-testid="flash-success"]').first.wait_for(
        state="attached", timeout=60_000
    )


def has_horizontal_overflow(page: Page) -> bool:
    return bool(
        page.evaluate(
            "() => document.documentElement.scrollWidth >"
            " document.documentElement.clientWidth + 1"
        )
    )


def clipped_elements(page: Page) -> list[str]:
    """Text nodes whose content is visually cut off."""
    return page.evaluate(
        """() => {
            const selectors = [
                '[data-testid="stMetricValue"]',
                '[data-testid="stMetricLabel"]',
                'button',
                '.aml-title',
            ];
            const clipped = [];
            for (const selector of selectors) {
                for (const element of document.querySelectorAll(selector)) {
                    const style = getComputedStyle(element);
                    if (style.overflow === 'visible' && style.textOverflow !== 'ellipsis') {
                        continue;
                    }
                    if (element.scrollWidth > element.clientWidth + 1) {
                        clipped.push(selector + ': ' + element.textContent.trim().slice(0, 40));
                    }
                }
            }
            return clipped;
        }"""
    )
