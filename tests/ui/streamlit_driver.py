"""Playwright helpers for driving the Streamlit apps.

Every helper waits for a concrete DOM state — a widget, an option, a marker
value — instead of sleeping. `marker(...)` reads the hidden `data-testid`
anchors the apps render for exactly this purpose.
"""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect

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


def expect_flash(
    page: Page, needle: str, kind: str = "success", timeout: int = DEFAULT_TIMEOUT
) -> None:
    """Wait for a flash message of `kind` whose text contains `needle`.

    A command that ends in `st.rerun()` is only finished once its message is on
    screen; waiting for the message is what makes the following database read
    deterministic.
    """
    page.wait_for_function(
        f"([id, needle]) => {{ const values = ({_FRESH_MARKERS})(id);"
        " return values.some(text => text.includes(needle)); }",
        arg=[f"flash-{kind}", needle],
        timeout=timeout,
    )


def wait_idle(page: Page, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Wait until Streamlit has finished the current script run.

    The running indicator alone is not enough: it appears with a delay, so a
    check right after an interaction can pass while the rerun is still on its
    way. Streamlit also marks every container of the previous render
    `data-stale="true"` for the whole rerun, and that flag is set immediately.
    """
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')"
        " && !document.querySelector('[data-stale=\"true\"]')",
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


#: A widget with a `help=` tooltip renders a hidden button of its own *before*
#: the real control, so every button lookup is filtered by visibility.
BUTTON = "button:visible"


def click_button(page: Page, key: str) -> None:
    button = widget(page, key).locator(BUTTON).first
    button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    expect(button).to_be_enabled(timeout=DEFAULT_TIMEOUT)
    button.click()
    wait_idle(page)


def button_is_disabled(page: Page, key: str) -> bool:
    button = widget(page, key).locator(BUTTON).first
    button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return button.is_disabled()


def _combobox(page: Page, key: str) -> Locator:
    """Streamlit renders selectboxes as a react-aria combobox input."""
    control = widget(page, key).locator('input[role="combobox"]').first
    control.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return control


#: Options of a *closed* listbox stay in the DOM, so every option locator is
#: filtered by `:visible`; otherwise `.first` resolves to a leftover of the
#: previous selectbox and never becomes visible.
OPTION = '[role="option"]:visible'


def _open_listbox(page: Page, key: str) -> Locator:
    """Open a selectbox and return the locator of its visible options.

    A click that lands while Streamlit is swapping the DOM is simply lost, so
    the attempt is repeated instead of being waited on forever.
    """
    options = page.locator(OPTION)
    last: Exception | None = None
    for attempt in range(3):
        try:
            control = _combobox(page, key)
            control.scroll_into_view_if_needed()
            control.click()
            options.first.wait_for(
                state="visible",
                timeout=5_000 if attempt < 2 else DEFAULT_TIMEOUT,
            )
            return options
        except PlaywrightError as error:
            last = error
            page.keyboard.press("Escape")
            wait_idle(page)
    raise AssertionError(f"listbox of {key!r} never opened: {last}")


def select_options(page: Page, key: str) -> list[str]:
    """Open a selectbox, read the offered labels and close it again."""
    options = _open_listbox(page, key)
    labels = [(text or "").strip() for text in options.all_text_contents()]
    page.keyboard.press("Escape")
    return labels


def choose_option(page: Page, key: str, label: str) -> None:
    """Pick an option by typing it: works at every viewport width.

    Real key events are used because the react-aria combobox only opens and
    filters its listbox in response to them. Narrow viewports occasionally
    swallow the first interaction, so the attempt is repeated once.
    """
    option = page.locator(OPTION).filter(has_text=label).first
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
            option.wait_for(
                state="visible", timeout=5_000 if attempt < 2 else DEFAULT_TIMEOUT
            )
            option.click()
            break
        except PlaywrightError as error:
            # A narrow viewport hiccup, or an element replaced by a rerun.
            last_error = error
            page.keyboard.press("Escape")
            wait_idle(page)
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
    """Load an app and wait for its auth state to settle.

    `pending` is the transient state while the cookie component answers, so it
    is never an outcome a test may observe.
    """
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function(
        f"() => {{ const values = ({_FRESH_MARKERS})('auth-state');"
        " return values.length > 0 && values[values.length - 1] !== 'pending'; }",
        timeout=60_000,
    )


def open_tab(page: Page, label: str) -> None:
    """Switch to a `st.tabs` panel and wait until it is the selected one."""
    tab = page.get_by_role("tab", name=label, exact=True).first
    tab.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    tab.click()
    expect(tab).to_have_attribute("aria-selected", "true", timeout=DEFAULT_TIMEOUT)
    wait_idle(page)


def open_page(page: Page, title: str) -> None:
    """Follow a `st.navigation` sidebar link and wait for that page."""
    link = page.locator('[data-testid="stSidebarNavLink"]').filter(has_text=title).first
    link.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    link.click()
    expect(link).to_have_attribute("aria-current", "page", timeout=DEFAULT_TIMEOUT)
    wait_idle(page)


def check(page: Page, key: str, checked: bool = True) -> None:
    """Bring a keyed checkbox to `checked` and let the rerun settle."""
    box = widget(page, key).locator("input[type='checkbox']").first
    box.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    if box.is_checked() != checked:
        widget(page, key).locator("label").first.click()
        expect(box).to_be_checked(checked=checked, timeout=DEFAULT_TIMEOUT)
    wait_idle(page)


def login(page: Page, url: str, email: str, password: str, admin: bool = False) -> None:
    open_app(page, url)
    if marker(page, "auth-state") == "authenticated":
        return
    prefix = "admin" if admin else "login"
    if not admin:
        open_tab(page, "Вход")
    fill_text(page, f"{prefix}_email", email)
    fill_text(page, f"{prefix}_password", password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect_marker(page, "auth-state", "authenticated", timeout=60_000)


def logout(page: Page) -> None:
    click_button(page, "logout")
    expect_marker(page, "auth-state", "anonymous", timeout=60_000)


def register(page: Page, url: str, email: str, display_name: str, password: str) -> None:
    open_app(page, url)
    open_tab(page, "Регистрация")
    fill_text(page, "register_name", display_name)
    fill_text(page, "register_email", email)
    fill_text(page, "register_password", password)
    fill_text(page, "register_password_repeat", password)
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


def streamlit_theme_options(page: Page) -> list[str]:
    """Open Streamlit's own menu and return its theme choices."""
    page.locator('[data-testid="stMainMenuButton"]').click()
    options = ["System", "Light", "Dark"]
    for option in options:
        page.get_by_text(option, exact=True).wait_for(
            state="visible", timeout=DEFAULT_TIMEOUT
        )
    page.keyboard.press("Escape")
    return options
