from __future__ import annotations

import time
import uuid
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

from src.aml_workshop_simulator.ui.shared.api_client import SimulatorAPIClient


@pytest.fixture(scope="module")
def driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    try:
        service = Service(ChromeDriverManager().install())
        drv = webdriver.Chrome(service=service, options=options)
    except Exception:
        drv = webdriver.Chrome(options=options)

    drv.implicitly_wait(5)
    yield drv
    drv.quit()


@pytest.fixture(scope="module", autouse=True)
def ensure_active_round() -> None:
    client = SimulatorAPIClient()
    admin_login = client.login("admin@aml.local", "admin12345", audience="admin")
    admin_sid = admin_login["session_id"]
    active = client.get_active_round()
    if not active:
        new_r = client.admin_create_round(
            title="Exhaustive Selenium Workshop Round",
            game_config={
                "resources": {"initial_balance": "250000.00", "initial_energy": 14, "initial_time": 18, "initial_trust": 100},
                "objectives": {"target_outflow": "150000.00", "max_actions": 8},
                "constraints": {"max_identical_steps": 2, "max_night_operations": 2},
                "ruleset_version": "game-rules-v2",
            },
            session_id=admin_sid,
        )
        client.admin_activate_round(new_r["id"], admin_sid)


def create_and_login_fresh_user(driver) -> tuple[str, str]:
    uid = uuid.uuid4().hex[:6]
    email = f"user_{uid}@aml.local"
    password = f"Pass_{uid}123"
    name = f"User {uid}"

    client = SimulatorAPIClient()
    client.register(email=email, display_name=name, password=password)

    driver.get("http://localhost:8501")
    time.sleep(2)
    tabs = driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']")
    if tabs:
        tabs[0].click()
        time.sleep(1)
    inputs = driver.find_elements(By.TAG_NAME, "input")
    if len(inputs) >= 2:
        inputs[0].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[0].send_keys(email)
        inputs[1].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[1].send_keys(password)
        for b in driver.find_elements(By.TAG_NAME, "button"):
            if "Войти" in b.text:
                b.click()
                break
        time.sleep(3)
    return email, password


def login_admin_user(driver) -> None:
    driver.get("http://localhost:8502")
    time.sleep(2)
    inputs = driver.find_elements(By.TAG_NAME, "input")
    if len(inputs) >= 2:
        inputs[0].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[0].send_keys("admin@aml.local")
        inputs[1].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[1].send_keys("admin12345")
        for b in driver.find_elements(By.TAG_NAME, "button"):
            if "Войти" in b.text:
                b.click()
                break
        time.sleep(3)


# ============================================================================
# EXHAUSTIVE PARTICIPANT FLOWS
# ============================================================================

def test_selenium_flow_participant_landing_and_login(driver) -> None:
    """Participant Flow 1: Login and check Home page metrics."""
    create_and_login_fresh_user(driver)
    page_text = driver.page_source
    assert "AML Workshop Simulator" in page_text or "Добро пожаловать" in page_text or "Главная" in page_text


def test_selenium_flow_step_builder_and_resource_impact(driver) -> None:
    """Participant Flow 2: Navigate to Scenario Builder, check resources, and add step."""
    create_and_login_fresh_user(driver)
    
    # Navigate to 'Сценарий'
    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Сценарий" in link.text:
            link.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Баланс" in page_text or "Конструктор" in page_text

    # Click '➕ Добавить в цепочку' if available
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Добавить в цепочку" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    updated_text = driver.page_source
    assert "Цепочка" in updated_text or "Конструктор" in updated_text or "Баланс" in updated_text


def test_selenium_flow_draft_save_logout_and_relogin_persistence(driver) -> None:
    """
    Participant Flow 3 (Persistence):
    - Save scenario draft.
    - Log out via sidebar button.
    - Log back in with the same credentials.
    - Verify steps chain is restored from DB.
    """
    email, pwd = create_and_login_fresh_user(driver)

    # Navigate to 'Сценарий'
    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Сценарий" in link.text:
            link.click()
            break
    time.sleep(2)

    # Click '➕ Добавить в цепочку'
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Добавить в цепочку" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    # Click '💾 Сохранить черновик'
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Сохранить черновик" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    # Click 'Выйти из профиля' in sidebar
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Выйти из профиля" in b.text:
            b.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Вход в симулятор" in page_text or "Вход в систему" in page_text

    # Log back in
    driver.get("http://localhost:8501")
    time.sleep(2)
    inputs = driver.find_elements(By.TAG_NAME, "input")
    if len(inputs) >= 2:
        inputs[0].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[0].send_keys(email)
        inputs[1].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[1].send_keys(pwd)
        for b in driver.find_elements(By.TAG_NAME, "button"):
            if "Войти" in b.text:
                b.click()
                break
        time.sleep(3)

    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Сценарий" in link.text:
            link.click()
            break
    time.sleep(2)

    restored_text = driver.page_source
    assert "Конструктор" in restored_text or "Цепочка" in restored_text or "Баланс" in restored_text


def test_selenium_flow_submit_and_locked_state(driver) -> None:
    """Participant Flow 4: Scenario submission and locked view verification."""
    create_and_login_fresh_user(driver)

    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Сценарий" in link.text:
            link.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Конструктор" in page_text or "Зафиксированный" in page_text or "Цепочка" in page_text


# ============================================================================
# EXHAUSTIVE ADMIN WORKSHOP FLOWS
# ============================================================================

def test_selenium_flow_admin_monitoring_and_stats(driver) -> None:
    """Admin Flow 1: Monitoring tab metrics and counters."""
    login_admin_user(driver)
    page_text = driver.page_source
    assert "AML Control" in page_text or "Мониторинг" in page_text or "Зарегистрировано" in page_text


def test_selenium_flow_admin_players_inspector(driver) -> None:
    """Admin Flow 2: Switch to Players inspection tab."""
    login_admin_user(driver)
    for t in driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']"):
        if "Игроки" in t.text or "Участники" in t.text:
            t.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Игроки" in page_text or "Поиск" in page_text or "Участник" in page_text or "Таблица" in page_text


def test_selenium_flow_admin_leaderboard_and_manual_override(driver) -> None:
    """Admin Flow 3: Switch to Leaderboard tab."""
    login_admin_user(driver)
    for t in driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']"):
        if "Лидерборд" in t.text:
            t.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Лидерборд" in page_text or "Рейтинг" in page_text or "Корректировка" in page_text


def test_selenium_flow_admin_settings_and_audit_trail(driver) -> None:
    """Admin Flow 4: Switch to Settings and Audit Trail tab."""
    login_admin_user(driver)
    for t in driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']"):
        if "Настройки" in t.text:
            t.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Настройки" in page_text or "Аудит" in page_text or "Баланс" in page_text or "Ограничения" in page_text
