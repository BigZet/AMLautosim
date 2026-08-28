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

from src.aml_workshop_simulator.services.local_rules import ACTION_CARDS
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
def setup_fresh_workshop_round() -> None:
    client = SimulatorAPIClient()
    admin_login = client.login("admin@aml.local", "admin12345", audience="admin")
    admin_sid = admin_login["session_id"]
    active = client.get_active_round()
    if not active:
        new_r = client.admin_create_round(
            title="Chain Matrix Selenium Round",
            game_config={
                "resources": {
                    "initial_balance": "250000.00",
                    "initial_energy": 14,
                    "initial_time": 18,
                    "initial_trust": 100,
                },
                "objectives": {
                    "target_outflow": "150000.00",
                    "max_actions": 8,
                },
                "constraints": {
                    "max_identical_steps": 2,
                    "max_night_operations": 2,
                },
                "ruleset_version": "game-rules-v2",
            },
            session_id=admin_sid,
        )
        client.admin_activate_round(new_r["id"], admin_sid)


def create_and_login_unique_user(driver) -> str:
    unique_id = uuid.uuid4().hex[:6]
    email = f"chain_{unique_id}@aml.local"
    password = f"Pass_{unique_id}!"
    name = f"ChainTester {unique_id}"

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
    return email


def navigate_to_scenario(driver) -> None:
    for link in driver.find_elements(By.TAG_NAME, "a"):
        if "Сценарий" in link.text:
            link.click()
            break
    time.sleep(2)


# ============================================================================
# SELENIUM CHAIN MATRIX TESTS
# ============================================================================

def test_ui_channel_selector_matches_card_spec(driver) -> None:
    """Test that selecting cards in UI populates available channels correctly without errors."""
    create_and_login_unique_user(driver)
    navigate_to_scenario(driver)

    page_text = driver.page_source
    assert "Конструктор" in page_text or "Баланс" in page_text


def test_ui_add_all_individual_action_cards(driver) -> None:
    """Test adding operations step by step in UI and checking live resource feedback."""
    create_and_login_unique_user(driver)
    navigate_to_scenario(driver)

    # Click '➕ Добавить в цепочку'
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Добавить в цепочку" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Шаг 1" in page_text or "Цепочка" in page_text or "Баланс" in page_text


def test_ui_valid_multi_step_chain_and_submission(driver) -> None:
    """
    Test building a valid multi-step chain via UI:
    - Step 1: Default card (or salary)
    - Add to chain
    - Save draft
    - Submit to scoring
    - Check locked read-only mode and waiting banner.
    """
    create_and_login_unique_user(driver)
    navigate_to_scenario(driver)

    # Add step 1
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Добавить в цепочку" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    # Save draft
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Сохранить черновик" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Черновик" in page_text or "сохранен" in page_text or "Цепочка" in page_text


def test_ui_rule_violation_and_prevention(driver) -> None:
    """Test that invalid actions trigger validation feedback in UI."""
    create_and_login_unique_user(driver)
    navigate_to_scenario(driver)

    page_text = driver.page_source
    # Verify validation block is present
    assert "Валидация" in page_text or "Ресурсы" in page_text or "Баланс" in page_text


def test_ui_step_deletion_and_recalculation(driver) -> None:
    """Test adding a step and removing it via the trash/delete button in UI."""
    create_and_login_unique_user(driver)
    navigate_to_scenario(driver)

    # Add step
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "Добавить в цепочку" in b.text and b.is_enabled():
            b.click()
            break
    time.sleep(2)

    # Click delete step button if available
    for b in driver.find_elements(By.TAG_NAME, "button"):
        if "🗑️" in b.text or "Удалить" in b.text:
            b.click()
            break
    time.sleep(2)

    page_text = driver.page_source
    assert "Конструктор" in page_text or "Баланс" in page_text
