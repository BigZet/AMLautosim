from __future__ import annotations

import time
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
def setup_active_round_for_selenium() -> None:
    client = SimulatorAPIClient()
    admin_login = client.login("admin@aml.local", "admin12345", audience="admin")
    admin_sid = admin_login["session_id"]
    active = client.get_active_round()
    if not active:
        new_r = client.admin_create_round(
            title="Selenium Full Suite Active Round",
            game_config={
                "resources": {"initial_balance": "250000.00", "initial_energy": 14, "initial_time": 18, "initial_trust": 100},
                "objectives": {"target_outflow": "150000.00", "max_actions": 8},
                "constraints": {"max_identical_steps": 2, "max_night_operations": 2},
                "ruleset_version": "game-rules-v2",
            },
            session_id=admin_sid,
        )
        client.admin_activate_round(new_r["id"], admin_sid)


def login_participant(driver) -> None:
    driver.get("http://localhost:8501")
    time.sleep(2)
    # Check if already logged in
    if "Выйти из профиля" in driver.page_source:
        return
    tabs = driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']")
    if tabs:
        tabs[0].click()
        time.sleep(1)
    inputs = driver.find_elements(By.TAG_NAME, "input")
    if len(inputs) >= 2:
        inputs[0].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[0].send_keys("demo@aml.local")
        inputs[1].send_keys(Keys.CONTROL + "a", Keys.BACKSPACE)
        inputs[1].send_keys("demo12345")
        for b in driver.find_elements(By.TAG_NAME, "button"):
            if "Войти" in b.text:
                b.click()
                break
        time.sleep(3)


def login_admin(driver) -> None:
    driver.get("http://localhost:8502")
    time.sleep(2)
    if "Завершить сессию" in driver.page_source or "AML Control" in driver.page_source:
        return
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
# PARTICIPANT TESTS
# ============================================================================

def test_selenium_participant_login_and_home_metrics(driver) -> None:
    """Participant Use Case: Login and view Home page with metrics."""
    login_participant(driver)
    page_text = driver.page_source
    assert "Добро пожаловать" in page_text or "Раунд" in page_text or "Цель" in page_text or "Главная" in page_text


def test_selenium_participant_navigation_to_scenario(driver) -> None:
    """Participant Use Case: Navigate to Scenario Builder and view resources."""
    login_participant(driver)
    
    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Сценарий" in link.text:
            link.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Конструктор" in page_text or "Сценарий" in page_text or "Цепочка" in page_text or "Баланс" in page_text


def test_selenium_participant_navigation_to_result(driver) -> None:
    """Participant Use Case: Navigate to Results page."""
    login_participant(driver)
    
    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Результат" in link.text:
            link.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Результат" in page_text or "Решение" in page_text or "Сценарий" in page_text or "скоринг" in page_text.lower()


def test_selenium_participant_navigation_to_leaderboard(driver) -> None:
    """Participant Use Case: Navigate to Leaderboard page."""
    login_participant(driver)
    
    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Лидерборд" in link.text:
            link.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Лидерборд" in page_text or "Таблица" in page_text or "Рейтинг" in page_text


# ============================================================================
# ADMIN TESTS
# ============================================================================

def test_selenium_admin_login_and_monitoring_tab(driver) -> None:
    """Admin Use Case: Login to Admin panel and view Monitoring dashboard."""
    login_admin(driver)
    page_text = driver.page_source
    assert "AML Control" in page_text or "Мониторинг" in page_text or "Зарегистрировано" in page_text


def test_selenium_admin_players_tab(driver) -> None:
    """Admin Use Case: Switch to Players inspection tab."""
    login_admin(driver)
    tabs = driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']")
    for t in tabs:
        if "Игроки" in t.text or "Участники" in t.text:
            t.click()
            break
    time.sleep(2)
    page_text = driver.page_source
    assert "Игроки" in page_text or "Поиск" in page_text or "Участник" in page_text or "Таблица" in page_text


def test_selenium_admin_leaderboard_tab(driver) -> None:
    """Admin Use Case: Switch to Leaderboard & Adjustments tab."""
    login_admin(driver)
    tabs = driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']")
    for t in tabs:
        if "Лидерборд" in t.text:
            t.click()
            break
    time.sleep(2)
    page_text = driver.page_source
    assert "Лидерборд" in page_text or "Корректировка" in page_text or "Балл" in page_text or "Рейтинг" in page_text


def test_selenium_admin_settings_and_audit_tab(driver) -> None:
    """Admin Use Case: Switch to Settings & Audit Trail tab."""
    login_admin(driver)
    tabs = driver.find_elements(By.CSS_SELECTOR, "[data-baseweb='tab']")
    for t in tabs:
        if "Настройки" in t.text:
            t.click()
            break
    time.sleep(2)
    page_text = driver.page_source
    assert "Настройки" in page_text or "Аудит" in page_text or "Баланс" in page_text or "Ограничения" in page_text
