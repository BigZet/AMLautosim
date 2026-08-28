from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.aml_workshop_simulator.api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_active_round() -> None:
    # Login as admin to ensure we have an active round
    admin_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@aml.local",
            "password": "admin12345",
            "audience": "admin"},
    )
    if admin_login.status_code == 200:
        admin_headers = {"X-Session-ID": admin_login.json()["session_id"]}
        active_round = client.get("/api/v1/rounds/active").json()
        if not active_round:
            # Create and activate a fresh test round
            new_round = client.post(
                "/api/v1/admin/rounds",
                json={
                    "title": "Тестовый раунд",
                    "game_config": {
                        "resources": {
                            "initial_balance": "250000.00",
                            "initial_energy": 14,
                            "initial_time": 18,
                            "initial_trust": 100},
                        "objectives": {
                            "target_outflow": "150000.00",
                            "max_actions": 8},
                        "constraints": {
                            "max_identical_steps": 2,
                            "max_night_operations": 2},
                        "ruleset_version": "game-rules-v2",
                    },
                },
                headers=admin_headers,
            ).json()
            client.post(
                f"/api/v1/admin/rounds/{new_round['id']}/activate", headers=admin_headers)


def test_health_endpoints() -> None:
    res_live = client.get("/health/live")
    assert res_live.status_code == 200
    assert res_live.json()["status"] == "ok"

    res_ready = client.get("/health/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"


def test_auth_and_participant_flow() -> None:
    # 1. Login with demo user
    login_res = client.post(
        "/api/v1/auth/login",
        json={
            "email": "demo@aml.local",
            "password": "demo12345",
            "audience": "play"},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    session_id = login_data["session_id"]
    headers = {"X-Session-ID": session_id}

    # 2. Get active round
    round_res = client.get("/api/v1/rounds/active")
    assert round_res.status_code == 200
    active_round = round_res.json()
    assert active_round is not None
    round_id = active_round["id"]

    # 3. Get cards for round
    cards_res = client.get(f"/api/v1/rounds/{round_id}/cards")
    assert cards_res.status_code == 200
    cards = cards_res.json()
    assert len(cards) >= 8

    # 4. Put scenario draft
    steps_payload = [
        {
            "card_code": "salary",
            "amount": 100000,
            "frequency": 1,
            "context": {
                "country_risk": "low",
                "recipient_type": "known_counterparty",
                "time_of_day": "day",
                "velocity": "normal",
                "channel": "bank",
                "has_documents": True,
            },
            "action_details": {
                "employer_profile": "verified_employer",
                "income_basis": "payroll_registry",
            },
        },
        {
            "card_code": "card_transfer",
            "amount": 50000,
            "frequency": 3,
            "context": {
                "country_risk": "low",
                "recipient_type": "known_counterparty",
                "time_of_day": "day",
                "velocity": "normal",
                "channel": "mobile",
                "has_documents": True,
            },
            "action_details": {
                "transfer_purpose": "family_support",
                "recipient_relationship": "family",
            },
        },
    ]

    put_res = client.put(
        f"/api/v1/rounds/{round_id}/scenario",
        json={"expected_revision": 0, "steps": steps_payload},
        headers=headers,
    )
    assert put_res.status_code == 200
    scenario_data = put_res.json()
    assert scenario_data["status"] == "draft"
    assert scenario_data["resources"]["valid"] is True
    assert scenario_data["resources"]["goal_reached"] is True

    # 5. Submit scenario
    submit_res = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": scenario_data["revision"]},
        headers=headers,
    )
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "submitted"


def test_admin_flow_and_scoring() -> None:
    # 1. Login as admin
    admin_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@aml.local",
            "password": "admin12345",
            "audience": "admin"},
    )
    assert admin_login.status_code == 200
    admin_headers = {"X-Session-ID": admin_login.json()["session_id"]}

    # 2. Get active round
    active_round = client.get("/api/v1/rounds/active").json()
    assert active_round is not None
    round_id = active_round["id"]

    # 3. Check stats
    stats_res = client.get(
        f"/api/v1/admin/rounds/{round_id}/stats",
        headers=admin_headers)
    assert stats_res.status_code == 200
    assert stats_res.json()["submitted_scenarios"] >= 1

    # 4. Trigger scoring
    score_res = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers=admin_headers)
    assert score_res.status_code == 200
    score_data = score_res.json()
    assert score_data["status"] == "completed"
    assert score_data["scored_count"] >= 1

    # 5. Check public leaderboard
    lb_res = client.get(f"/api/v1/rounds/{round_id}/leaderboard")
    assert lb_res.status_code == 200
    rows = lb_res.json()["rows"]
    assert len(rows) >= 1
    assert rows[0]["rank"] == 1
