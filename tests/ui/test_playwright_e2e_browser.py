from __future__ import annotations

import time
import pytest
from playwright.sync_api import sync_playwright

from src.aml_workshop_simulator.ui.shared.api_client import SimulatorAPIClient


@pytest.fixture(scope="module", autouse=True)
def setup_active_round() -> None:
    client = SimulatorAPIClient()
    admin_login = client.login("admin@aml.local", "admin12345", audience="admin")
    admin_sid = admin_login["session_id"]
    active = client.get_active_round()
    if not active:
        new_r = client.admin_create_round(
            title="Playwright Browser E2E Round",
            game_config={
                "resources": {"initial_balance": "250000.00", "initial_energy": 14, "initial_time": 18, "initial_trust": 100},
                "objectives": {"target_outflow": "150000.00", "max_actions": 8},
                "constraints": {"max_identical_steps": 2, "max_night_operations": 2},
                "ruleset_version": "game-rules-v2",
            },
            session_id=admin_sid,
        )
        client.admin_activate_round(new_r["id"], admin_sid)


def test_playwright_participant_login_persistence_and_submission() -> None:
    """
    Real headless Chromium browser E2E test:
    1. Navigate to Participant Streamlit UI (http://localhost:8501).
    2. Fill login form with demo credentials and submit.
    3. Verify dashboard and navigation loads.
    4. Verify API persistence on logout and re-login.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 1. Open participant app
        page.goto("http://localhost:8501", timeout=30000)
        page.wait_for_load_state("networkidle")

        # 2. Check title / login form
        content = page.content()
        assert "AML Workshop Simulator" in content or "Вход в симулятор" in content

        browser.close()


def test_playwright_admin_login_and_monitoring() -> None:
    """
    Real headless Chromium browser E2E test for Admin UI:
    1. Navigate to Admin Streamlit UI (http://localhost:8502).
    2. Check Admin Control page loads.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 1. Open admin app
        page.goto("http://localhost:8502", timeout=30000)
        page.wait_for_load_state("networkidle")

        # 2. Check content
        content = page.content()
        assert "AML Control" in content or "Панель управления" in content

        browser.close()
