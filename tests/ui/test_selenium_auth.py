"""Registration and login through a real browser.

Every case drives the actual form the participant sees, waits for a concrete
state and asserts one specific outcome. Nothing here counts inputs, accepts
"one of several messages", or reaches around the UI to create an account
through the API — the registration form *is* what is under test.

Failures leave a screenshot, the page source and the browser console log in
`tests/artifacts/`.
"""

from __future__ import annotations

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
    unique_email,
)

selenium_webdriver = pytest.importorskip("selenium.webdriver")

from tests.ui.selenium_driver import (  # noqa: E402
    capture,
    click_text,
    click_text_twice,
    current_theme,
    emulate_viewport,
    expect_marker,
    field_value,
    fill,
    logout,
    marker,
    open_app,
    open_page,
    open_tab,
    page_contains,
    register,
    reset_viewport,
    text_of,
    toggle_theme,
    try_login,
    viewport_width,
    wait,
    wait_idle,
    widget,
)
from tests.ui.selenium_driver import login as ui_login  # noqa: E402

LONG_UNICODE_NICKNAME = "Ёжик-в-тумане " + "Ω" * 40


@pytest.fixture(scope="module")
def driver() -> Iterator[Any]:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,1000")
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
def isolated_browser(driver: Any, reset_state: Stack, request) -> Iterator[None]:
    """A clean browser session per test, and artefacts when one fails."""
    driver.get(reset_state.play_url)
    driver.delete_all_cookies()
    driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    try:
        yield
    finally:
        if getattr(request.node, "_selenium_failed", False):
            capture(driver, ARTIFACTS, request.node.name)


def accounts_with(email: str) -> list[tuple]:
    return db_query("SELECT id, display_name FROM users WHERE email = %s", (email,))


def active_sessions(email: str) -> int:
    rows = db_query(
        "SELECT count(*) FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE u.email = %s AND s.revoked_at IS NULL",
        (email,),
    )
    return int(rows[0][0])


def error_text(driver: Any) -> str:
    """The message the form is currently showing, whatever produced it."""
    return text_of(driver, '[data-testid="auth-error"], [data-testid="flash-error"]')


# --------------------------------------------------------------------------
# 1. The two tabs exist and switch
# --------------------------------------------------------------------------


def test_login_and_registration_tabs_are_both_reachable(
    reset_state: Stack, driver: Any
) -> None:
    open_app(driver, reset_state.play_url)
    assert marker(driver, "auth-state") == "anonymous"

    open_tab(driver, "Вход")
    widget(driver, "login_email")
    widget(driver, "login_password")

    open_tab(driver, "Регистрация")
    for key in (
        "register_name",
        "register_email",
        "register_password",
        "register_password_repeat",
    ):
        widget(driver, key)


# --------------------------------------------------------------------------
# 2. Successful registration
# --------------------------------------------------------------------------


def test_registration_creates_exactly_one_account(reset_state: Stack, driver: Any) -> None:
    email = unique_email("new")
    register(driver, reset_state.play_url, "Новый игрок", email, PARTICIPANT_PASSWORD)

    wait(driver).until(
        lambda d: d.find_elements(
            "css selector", '[data-testid="flash-success"]'
        ),
        "the success message never appeared",
    )
    assert "Регистрация выполнена" in text_of(driver, '[data-testid="flash-success"]')
    assert accounts_with(email) == [(accounts_with(email)[0][0], "Новый игрок")]
    assert active_sessions(email) == 0, "registration must not sign anybody in"


# --------------------------------------------------------------------------
# 3. Required fields
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing, expected",
    [
        ("register_name", "Укажите игровой псевдоним."),
        ("register_email", "Укажите email."),
        ("register_password", "Укажите пароль."),
        ("register_password_repeat", "Повторите пароль."),
    ],
)
def test_every_registration_field_is_required(
    reset_state: Stack, driver: Any, missing: str, expected: str
) -> None:
    email = unique_email("required")
    values = {
        "register_name": "Игрок",
        "register_email": email,
        "register_password": PARTICIPANT_PASSWORD,
        "register_password_repeat": PARTICIPANT_PASSWORD,
    }
    values[missing] = ""

    open_app(driver, reset_state.play_url)
    open_tab(driver, "Регистрация")
    for key, value in values.items():
        if value:
            fill(driver, key, value)
    click_text(driver, "Зарегистрироваться")

    assert expected in error_text(driver)
    assert accounts_with(email) == []


# --------------------------------------------------------------------------
# 4. Malformed email
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad_email", ["игрок", "player@", "player@localhost"])
def test_a_malformed_email_is_refused(
    reset_state: Stack, driver: Any, bad_email: str
) -> None:
    register(driver, reset_state.play_url, "Игрок", bad_email, PARTICIPANT_PASSWORD)
    assert "Email" in error_text(driver)
    assert db_query("SELECT count(*) FROM users WHERE email = %s", (bad_email,)) == [(0,)]


# --------------------------------------------------------------------------
# 5. Weak password
# --------------------------------------------------------------------------


def test_a_short_password_is_refused_with_the_exact_rule(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("weak")
    register(driver, reset_state.play_url, "Игрок", email, "short1234")
    assert "не менее 10 символов" in error_text(driver)
    assert accounts_with(email) == []


def test_a_password_of_exactly_ten_characters_is_accepted(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("boundary")
    register(driver, reset_state.play_url, "Игрок", email, "0123456789")
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "a ten character password was refused",
    )
    assert len(accounts_with(email)) == 1


# --------------------------------------------------------------------------
# 6. Password confirmation
# --------------------------------------------------------------------------


def test_mismatched_passwords_are_refused_and_input_is_kept(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("mismatch")
    register(
        driver,
        reset_state.play_url,
        "Игрок",
        email,
        PARTICIPANT_PASSWORD,
        confirmation="another-password",
    )
    assert "Пароли не совпадают." in error_text(driver)
    assert accounts_with(email) == []
    # The work already typed must survive the error.
    assert field_value(driver, "register_name") == "Игрок"
    assert field_value(driver, "register_email") == email


# --------------------------------------------------------------------------
# 7. Duplicate email
# --------------------------------------------------------------------------


def test_a_duplicate_normalised_email_is_refused(reset_state: Stack, driver: Any) -> None:
    email = unique_email("dup")
    register(driver, reset_state.play_url, "Первый", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "the first registration never succeeded",
    )

    register(
        driver,
        reset_state.play_url,
        "Второй",
        email.upper(),
        PARTICIPANT_PASSWORD,
    )
    assert "уже зарегистрирован" in error_text(driver)
    assert len(accounts_with(email)) == 1
    assert accounts_with(email)[0][1] == "Первый"


# --------------------------------------------------------------------------
# 8. Whitespace and letter case
# --------------------------------------------------------------------------


def test_email_is_normalised_before_it_reaches_the_database(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("case")
    register(
        driver,
        reset_state.play_url,
        "  Игрок с пробелами  ",
        f"  {email.upper()}  ",
        PARTICIPANT_PASSWORD,
    )
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration with padded input never succeeded",
    )
    stored = accounts_with(email)
    assert len(stored) == 1
    assert stored[0][1] == "Игрок с пробелами"

    # The very same address in another case logs in.
    ui_login(driver, reset_state.play_url, f"  {email.title()}  ", PARTICIPANT_PASSWORD)
    assert marker(driver, "auth-state") == "authenticated"


# --------------------------------------------------------------------------
# 9. Unicode and long nicknames
# --------------------------------------------------------------------------


def test_a_long_unicode_nickname_is_stored_and_displayed(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("unicode")
    register(driver, reset_state.play_url, LONG_UNICODE_NICKNAME, email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "a unicode nickname was refused",
    )
    assert accounts_with(email)[0][1] == LONG_UNICODE_NICKNAME

    ui_login(driver, reset_state.play_url, email, PARTICIPANT_PASSWORD)
    assert text_of(driver, '[data-testid="current-user"]') == LONG_UNICODE_NICKNAME


# --------------------------------------------------------------------------
# 10. Successful login
# --------------------------------------------------------------------------


def test_a_freshly_registered_player_can_sign_in(reset_state: Stack, driver: Any) -> None:
    email = unique_email("login")
    register(driver, reset_state.play_url, "Свежий игрок", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    ui_login(driver, reset_state.play_url, email, PARTICIPANT_PASSWORD)
    assert text_of(driver, '[data-testid="current-user"]') == "Свежий игрок"
    assert active_sessions(email) == 1


# --------------------------------------------------------------------------
# 11. Wrong password
# --------------------------------------------------------------------------


def test_a_wrong_password_is_refused_without_a_session(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("wrongpass")
    register(driver, reset_state.play_url, "Игрок", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    try_login(driver, reset_state.play_url, email, "definitely-not-it")
    assert error_text(driver) == "Неверный email или пароль."
    assert marker(driver, "auth-state") == "anonymous"
    assert active_sessions(email) == 0


# --------------------------------------------------------------------------
# 12. Unknown account
# --------------------------------------------------------------------------


def test_an_unknown_email_does_not_reveal_whether_it_exists(
    reset_state: Stack, driver: Any
) -> None:
    known = unique_email("known")
    register(driver, reset_state.play_url, "Игрок", known, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    try_login(driver, reset_state.play_url, known, "definitely-not-it")
    for_existing = error_text(driver)

    try_login(driver, reset_state.play_url, unique_email("ghost"), "definitely-not-it")
    for_missing = error_text(driver)

    assert for_existing == for_missing == "Неверный email или пароль."


# --------------------------------------------------------------------------
# 13. Audience separation
# --------------------------------------------------------------------------


def test_a_participant_cannot_sign_into_the_admin_panel(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("audience")
    register(driver, reset_state.play_url, "Игрок", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    try_login(driver, reset_state.admin_url, email, PARTICIPANT_PASSWORD, admin=True)
    assert "Недостаточно прав" in error_text(driver)
    assert marker(driver, "auth-state") == "anonymous"
    assert active_sessions(email) == 0


def test_the_administrator_cannot_sign_into_the_player_app(
    reset_state: Stack, driver: Any
) -> None:
    try_login(driver, reset_state.play_url, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert "не участвует в игровом раунде" in error_text(driver)
    assert marker(driver, "auth-state") == "anonymous"


# --------------------------------------------------------------------------
# 14. Blocked participant
# --------------------------------------------------------------------------


def test_a_blocked_participant_cannot_sign_in(reset_state: Stack, driver: Any) -> None:
    stack = reset_state
    email = unique_email("blocked")
    register(driver, stack.play_url, "Нарушитель", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    admin_session = stack.request(
        "POST",
        "/api/v1/auth/login",
        {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "audience": "admin"},
    )["session_id"]
    round_id = stack.request("GET", "/api/v1/rounds/active")["id"]
    participant_id = accounts_with(email)[0][0]
    stack.request(
        "PUT",
        f"/api/v1/admin/rounds/{round_id}/participants/{participant_id}/access",
        {
            "blocked": True,
            "reason": "Нарушение правил мастер-класса",
            "expected_access_revision": 1,
        },
        session_id=admin_session,
    )

    try_login(driver, stack.play_url, email, PARTICIPANT_PASSWORD)
    assert "заблокирован" in error_text(driver)
    assert marker(driver, "auth-state") == "anonymous"


# --------------------------------------------------------------------------
# 15. Logout revokes the session
# --------------------------------------------------------------------------


def test_logout_revokes_the_session_and_the_cookie_cannot_be_replayed(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    email = unique_email("logout")
    register(driver, stack.play_url, "Уходящий", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )
    ui_login(driver, stack.play_url, email, PARTICIPANT_PASSWORD)
    assert active_sessions(email) == 1

    stolen = driver.get_cookie("aml_play_session_id")
    assert stolen is not None, "the session cookie was never set"

    logout(driver)
    assert active_sessions(email) == 0

    # Putting the revoked identifier back must not restore the session.
    driver.add_cookie(
        {"name": "aml_play_session_id", "value": stolen["value"], "path": "/"}
    )
    open_app(driver, stack.play_url)
    expect_marker(driver, "auth-state", "anonymous")


# --------------------------------------------------------------------------
# 16. The session survives navigation and reruns
# --------------------------------------------------------------------------


def test_the_session_survives_navigation_and_a_rerun(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("nav")
    register(driver, reset_state.play_url, "Навигатор", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )
    ui_login(driver, reset_state.play_url, email, PARTICIPANT_PASSWORD)

    open_page(driver, "Лидерборд")
    expect_marker(driver, "auth-state", "authenticated")
    open_page(driver, "Результат")
    expect_marker(driver, "auth-state", "authenticated")

    driver.refresh()
    expect_marker(driver, "auth-state", "authenticated")
    assert text_of(driver, '[data-testid="current-user"]') == "Навигатор"
    assert active_sessions(email) == 1


# --------------------------------------------------------------------------
# 17. Theme switching on the auth screens
# --------------------------------------------------------------------------


def test_the_theme_can_be_switched_on_the_login_screen_and_is_remembered(
    reset_state: Stack, driver: Any
) -> None:
    open_app(driver, reset_state.play_url)
    assert current_theme(driver) == "dark", "dark must be the starting appearance"

    switched = toggle_theme(driver, "theme_toggle_auth")
    assert switched == "light"

    background = driver.execute_script(
        "return getComputedStyle(document.body).backgroundColor;"
    )
    assert background == "rgb(245, 247, 246)"

    # A reload keeps the choice, and so does signing in.
    open_app(driver, reset_state.play_url)
    assert current_theme(driver) == "light"

    email = unique_email("theme")
    register(driver, reset_state.play_url, "Тема", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )
    ui_login(driver, reset_state.play_url, email, PARTICIPANT_PASSWORD)
    assert current_theme(driver) == "light"
    assert toggle_theme(driver, "theme_toggle_app") == "dark"


def test_the_admin_login_screen_has_its_own_theme_switch(
    reset_state: Stack, driver: Any
) -> None:
    open_app(driver, reset_state.admin_url)
    assert current_theme(driver) == "dark"
    assert toggle_theme(driver, "theme_toggle_auth") == "light"


# --------------------------------------------------------------------------
# 18. Mobile viewport
# --------------------------------------------------------------------------


def test_the_auth_screens_fit_a_mobile_viewport(reset_state: Stack, driver: Any) -> None:
    emulate_viewport(driver, 390, 844)
    try:
        open_app(driver, reset_state.play_url)
        open_tab(driver, "Регистрация")
        wait_idle(driver)

        width = viewport_width(driver)
        assert width == 390, f"the viewport was not emulated ({width}px)"

        overflow = driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth;"
        )
        assert overflow <= 1, f"the page scrolls sideways by {overflow}px"

        boxes = driver.execute_script(
            """
            const keys = ['register_name', 'register_email', 'register_password',
                          'register_password_repeat'];
            return keys.map(key => {
                const node = document.querySelector(`.st-key-${key} input`);
                if (!node) { return null; }
                const box = node.getBoundingClientRect();
                return {key, top: box.top, bottom: box.bottom,
                        left: box.left, right: box.right, width: box.width};
            });
            """
        )
        assert all(box is not None for box in boxes), boxes
        for box in boxes:
            assert box["width"] > 100, box
            assert box["left"] >= -1 and box["right"] <= width + 1, box
        for first, second in zip(boxes, boxes[1:], strict=False):
            assert first["bottom"] <= second["top"] + 1, (first, second)
    finally:
        reset_viewport(driver)


# --------------------------------------------------------------------------
# 19. The API is unreachable
# --------------------------------------------------------------------------


def test_an_unreachable_api_is_reported_to_the_participant(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    email = unique_email("offline")
    register(driver, stack.play_url, "Оффлайн", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    stack.stop_api()
    try:
        try_login(driver, stack.play_url, email, PARTICIPANT_PASSWORD)
        assert "Сервис недоступен" in error_text(driver)
        assert marker(driver, "auth-state") == "anonymous"
    finally:
        stack.start_api()

    # The service comes back and the same credentials work.
    ui_login(driver, stack.play_url, email, PARTICIPANT_PASSWORD)
    assert active_sessions(email) == 1


# --------------------------------------------------------------------------
# 20. Double submission
# --------------------------------------------------------------------------


def test_double_clicking_register_creates_one_account(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("double")
    open_app(driver, reset_state.play_url)
    open_tab(driver, "Регистрация")
    fill(driver, "register_name", "Дважды")
    fill(driver, "register_email", email)
    fill(driver, "register_password", PARTICIPANT_PASSWORD)
    fill(driver, "register_password_repeat", PARTICIPANT_PASSWORD)

    click_text_twice(driver, "Зарегистрироваться")
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]')
        or d.find_elements("css selector", '[data-testid="auth-error"]'),
        "the form never answered",
    )
    assert len(accounts_with(email)) == 1


def test_double_clicking_login_creates_one_session(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("doublelogin")
    register(driver, reset_state.play_url, "Дважды вхожу", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )

    open_app(driver, reset_state.play_url)
    open_tab(driver, "Вход")
    fill(driver, "login_email", email)
    fill(driver, "login_password", PARTICIPANT_PASSWORD)
    click_text_twice(driver, "Войти")

    expect_marker(driver, "auth-state", "authenticated")
    assert active_sessions(email) == 1


# --------------------------------------------------------------------------
# Two participants never mix
# --------------------------------------------------------------------------


def test_two_participants_in_one_browser_never_mix(
    reset_state: Stack, driver: Any
) -> None:
    stack = reset_state
    first_email = unique_email("first")
    second_email = unique_email("second")
    for email, name in ((first_email, "Первый"), (second_email, "Второй")):
        register(driver, stack.play_url, name, email, PARTICIPANT_PASSWORD)
        wait(driver).until(
            lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
            f"registration of {name} never succeeded",
        )

    ui_login(driver, stack.play_url, first_email, PARTICIPANT_PASSWORD)
    assert text_of(driver, '[data-testid="current-user"]') == "Первый"
    logout(driver)

    ui_login(driver, stack.play_url, second_email, PARTICIPANT_PASSWORD)
    assert text_of(driver, '[data-testid="current-user"]') == "Второй"
    assert not page_contains(driver, "Первый")
    assert active_sessions(first_email) == 0
    assert active_sessions(second_email) == 1


def test_a_registration_attempt_is_recorded_with_its_device(
    reset_state: Stack, driver: Any
) -> None:
    """The administrator can tell which browser a participant used."""
    stack = reset_state
    email = unique_email("device")
    register(driver, stack.play_url, "С браузером", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )
    ui_login(driver, stack.play_url, email, PARTICIPANT_PASSWORD)

    rows = db_query(
        "SELECT s.ip_address::text, s.user_agent FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE u.email = %s",
        (email,),
    )
    assert len(rows) == 1
    address, user_agent = rows[0]
    assert address
    assert "Chrome" in (user_agent or ""), user_agent


def test_the_session_cookie_carries_nothing_but_an_opaque_identifier(
    reset_state: Stack, driver: Any
) -> None:
    email = unique_email("cookie")
    register(driver, reset_state.play_url, "Печенька", email, PARTICIPANT_PASSWORD)
    wait(driver).until(
        lambda d: d.find_elements("css selector", '[data-testid="flash-success"]'),
        "registration never succeeded",
    )
    ui_login(driver, reset_state.play_url, email, PARTICIPANT_PASSWORD)

    cookie = driver.get_cookie("aml_play_session_id")
    assert cookie is not None
    value = cookie["value"]
    assert email.split("@")[0] not in value
    assert "Печенька" not in value
    assert PARTICIPANT_PASSWORD not in value
    assert len(value) >= 32
    # The stored form is a hash, never the identifier itself.
    assert db_query(
        "SELECT count(*) FROM sessions WHERE session_id_hash = %s", (value,)
    ) == [(0,)]
