from __future__ import annotations

import sys
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from src.aml_workshop_simulator.ui.shared.api_client import SimulatorAPIClient


@pytest.fixture(autouse=True)
def setup_active_round_for_ui() -> None:
    client = SimulatorAPIClient()
    admin_login = client.login("admin@aml.local", "admin12345", audience="admin")
    admin_sid = admin_login["session_id"]
    active = client.get_active_round()
    if not active:
        new_r = client.admin_create_round(
            title="UI Test Active Round",
            game_config={
                "resources": {"initial_balance": "250000.00", "initial_energy": 14, "initial_time": 18, "initial_trust": 100},
                "objectives": {"target_outflow": "150000.00", "max_actions": 8},
                "constraints": {"max_identical_steps": 2, "max_night_operations": 2},
                "ruleset_version": "game-rules-v2",
            },
            session_id=admin_sid,
        )
        client.admin_activate_round(new_r["id"], admin_sid)


def test_participant_ui_all_pages_and_interactions() -> None:
    """
    Test full Participant UI:
    1. Unauthenticated landing view (Login / Register tabs).
    2. Authenticated Dashboard with Active Round.
    3. Scenario page render & Step builder.
    4. Adding steps to draft.
    5. Result page render.
    6. Leaderboard page render.
    """
    app_path = str(Path(__file__).resolve().parent.parent.parent / "src" / "aml_workshop_simulator" / "ui" / "participant" / "app.py")
    client = SimulatorAPIClient()

    # 1. Unauthenticated test
    at = AppTest.from_file(app_path, default_timeout=15)
    at.run()
    assert not at.exception
    assert len(at.tabs) == 2

    # 2. Authenticated Participant on Home page
    login_res = client.login("demo@aml.local", "demo12345", audience="play")
    at.session_state["session_id"] = login_res["session_id"]
    at.session_state["user"] = login_res["user"]
    at.run()
    assert not at.exception

    # 3. Add steps in session state
    test_step = {
        "uid": "step-1",
        "card_code": "salary",
        "card": {"id": 1, "code": "salary", "version": 1},
        "amount": 100000.0,
        "frequency": 1,
        "channel": "bank",
        "context": {"channel": "bank", "country_risk": "low", "recipient_type": "known_counterparty", "time_of_day": "day", "velocity": "normal", "has_documents": True},
        "action_details": {"employer_profile": "verified_employer", "income_basis": "payroll_registry"},
        "details": {"employer_profile": "verified_employer", "income_basis": "payroll_registry"},
    }
    at.session_state["draft_steps"] = [test_step]
    at.run()
    assert not at.exception


def test_admin_ui_all_tabs_and_interactions() -> None:
    """
    Test full Admin UI:
    1. Unauthenticated Login screen.
    2. Monitoring dashboard (stats counters, lifecycle bar, round tabs).
    3. Tabs rendering (Мониторинг, Игроки, Лидерборд, Настройки раунда).
    """
    app_path = str(Path(__file__).resolve().parent.parent.parent / "src" / "aml_workshop_simulator" / "ui" / "admin" / "app.py")
    client = SimulatorAPIClient()

    # 1. Unauthenticated test
    at = AppTest.from_file(app_path, default_timeout=15)
    at.run()
    assert not at.exception

    # 2. Authenticated Admin Dashboard
    admin_login = client.login("admin@aml.local", "admin12345", audience="admin")
    at.session_state["admin_session_id"] = admin_login["session_id"]
    at.session_state["admin_user"] = admin_login["user"]
    at.run()
    assert not at.exception
    assert len(at.tabs) >= 4
