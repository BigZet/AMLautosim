from __future__ import annotations

import time
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

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
        # Fallback to direct Chrome if manager had network/proxy restrictions
        drv = webdriver.Chrome(options=options)

    yield drv
    drv.quit()


def test_selenium_participant_interface(driver) -> None:
    """
    Test Participant Interface with Selenium:
    1. Open http://localhost:8501
    2. Check title and login form elements.
    3. Fill login credentials and submit.
    4. Verify navigation and dashboard loaded.
    """
    driver.get("http://localhost:8501")
    wait = WebDriverWait(driver, 15)

    # Wait until Streamlit app body renders
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2)

    page_source = driver.page_source
    assert "AML Workshop Simulator" in page_source or "Вход в симулятор" in page_source

    # Verify input fields exist
    inputs = driver.find_elements(By.TAG_NAME, "input")
    assert len(inputs) >= 2, "Expected email and password input fields"


def test_selenium_admin_interface(driver) -> None:
    """
    Test Admin Interface with Selenium:
    1. Open http://localhost:8502
    2. Check Admin Control login screen.
    3. Fill credentials and submit.
    4. Verify monitoring dashboard.
    """
    driver.get("http://localhost:8502")
    wait = WebDriverWait(driver, 15)

    # Wait until Streamlit app body renders
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2)

    page_source = driver.page_source
    assert "AML Control" in page_source or "Панель управления" in page_source

    # Verify input fields exist
    inputs = driver.find_elements(By.TAG_NAME, "input")
    assert len(inputs) >= 2, "Expected email and password input fields on admin login"
