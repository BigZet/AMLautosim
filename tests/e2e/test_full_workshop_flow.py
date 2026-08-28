from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.aml_workshop_simulator.api.main import app
from src.aml_workshop_simulator.ui.shared.api_client import SimulatorAPIClient

client = TestClient(app)


def test_complete_e2e_workshop_lifecycle() -> None:
    """
    Exhaustive End-to-End Test simulating the full workshop lifecycle:
    1. Admin creates a new draft round #2 with custom config.
    2. Admin activates the new round.
    3. Multiple participants register and login.
    4. Participant 1 creates an invalid scenario (insufficient outflow) -> submit fails.
    5. Participant 1 fixes scenario with structured multi-step flow -> draft saves, submit succeeds.
    6. Participant 2 builds a high-risk crypto evasion scenario -> submit succeeds.
    7. Participant 3 saves a draft but doesn't submit.
    8. Admin inspects real-time stats (1 draft, 2 submitted).
    9. Admin inspects Participant 2's detailed chain and blocks Participant 2 with a reason.
    10. Blocked Participant 2 is rejected from accessing protected endpoints.
    11. Admin unblocks Participant 2.
    12. Admin triggers batch scoring -> 2 scenarios scored, 1 draft excluded.
    13. Both participants view their detailed results with factors and CatBoost features.
    14. Admin applies a leaderboard adjustment to Participant 1 with reason.
    15. Public and Admin leaderboard reflect updated rankings.
    16. Audit trail contains all recorded events.
    """
    # 1. Admin Login
    admin_login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@aml.local", "password": "admin12345", "audience": "admin"},
    )
    assert admin_login_res.status_code == 200
    admin_sid = admin_login_res.json()["session_id"]
    admin_headers = {"X-Session-ID": admin_sid}

    # 2. Check and complete any existing active round first (rule: only 1 active round at a time)
    active_prev = client.get("/api/v1/rounds/active").json()
    if active_prev:
        prev_id = active_prev["id"]
        # Submit a demo scenario so scoring succeeds
        demo_login = client.post("/api/v1/auth/login", json={"email": "demo@aml.local", "password": "demo12345", "audience": "play"}).json()
        demo_headers = {"X-Session-ID": demo_login["session_id"]}
        steps = [
            {"card_code": "salary", "amount": 100000, "frequency": 1, "context": {"channel": "bank", "has_documents": True}},
            {"card_code": "card_transfer", "amount": 100000, "frequency": 2, "context": {"channel": "mobile", "has_documents": True}},
        ]
        put_scen = client.put(f"/api/v1/rounds/{prev_id}/scenario", json={"expected_revision": 0, "steps": steps}, headers=demo_headers).json()
        client.post(f"/api/v1/rounds/{prev_id}/scenario/submit", json={"expected_revision": put_scen["revision"]}, headers=demo_headers)
        client.post(f"/api/v1/admin/rounds/{prev_id}/score", headers=admin_headers)

    # 3. Admin creates Round #2
    round_create_payload = {
        "title": "Мастер-класс AML: Сезон 2026",
        "game_config": {
            "resources": {
                "initial_balance": "300000.00",
                "initial_energy": 15,
                "initial_time": 20,
                "initial_trust": 100,
            },
            "objectives": {"target_outflow": "200000.00", "max_actions": 8},
            "constraints": {
                "max_identical_steps": 2,
                "max_night_operations": 2,
            },
            "ruleset_version": "game-rules-v2",
            "scoring": {"version": "risk-rules-v2"},
            "leaderboard": {"version": "leaderboard-v1"},
        },
    }
    r_create_res = client.post("/api/v1/admin/rounds", json=round_create_payload, headers=admin_headers)
    assert r_create_res.status_code == 201
    round_id = r_create_res.json()["id"]

    # 4. Admin activates Round #2
    r_act_res = client.post(f"/api/v1/admin/rounds/{round_id}/activate", headers=admin_headers)
    assert r_act_res.status_code == 200
    assert r_act_res.json()["status"] == "active"

    # 4. Register and Login Participant 1 (Alice)
    client.post("/api/v1/auth/register", json={"email": "alice@aml.local", "display_name": "Alice Fin", "password": "password123"})
    p1_login = client.post("/api/v1/auth/login", json={"email": "alice@aml.local", "password": "password123", "audience": "play"})
    assert p1_login.status_code == 200
    p1_headers = {"X-Session-ID": p1_login.json()["session_id"]}

    # 5. Register and Login Participant 2 (Bob)
    client.post("/api/v1/auth/register", json={"email": "bob@aml.local", "display_name": "Bob Stealth", "password": "password123"})
    p2_login = client.post("/api/v1/auth/login", json={"email": "bob@aml.local", "password": "password123", "audience": "play"})
    assert p2_login.status_code == 200
    p2_headers = {"X-Session-ID": p2_login.json()["session_id"]}
    p2_user_id = p2_login.json()["user"]["id"]

    # 6. Register and Login Participant 3 (Charlie)
    client.post("/api/v1/auth/register", json={"email": "charlie@aml.local", "display_name": "Charlie Idle", "password": "password123"})
    p3_login = client.post("/api/v1/auth/login", json={"email": "charlie@aml.local", "password": "password123", "audience": "play"})
    assert p3_login.status_code == 200
    p3_headers = {"X-Session-ID": p3_login.json()["session_id"]}

    # 7. Participant 1 puts invalid scenario (only 50k outflow when target is 200k)
    p1_invalid_steps = [
        {"card_code": "salary", "amount": 100000, "frequency": 1, "context": {"channel": "bank", "has_documents": True}},
        {"card_code": "card_transfer", "amount": 50000, "frequency": 1, "context": {"channel": "mobile", "has_documents": True}},
    ]
    p1_put_res = client.put(f"/api/v1/rounds/{round_id}/scenario", json={"expected_revision": 0, "steps": p1_invalid_steps}, headers=p1_headers)
    assert p1_put_res.status_code == 200
    p1_rev = p1_put_res.json()["revision"]

    # Submit should fail because target outflow (200k) is not reached
    p1_sub_fail = client.post(f"/api/v1/rounds/{round_id}/scenario/submit", json={"expected_revision": p1_rev}, headers=p1_headers)
    assert p1_sub_fail.status_code == 400
    assert "target_outflow_not_reached" in p1_sub_fail.json()["message"]

    # 8. Participant 1 updates scenario to reach 200k target outflow
    p1_valid_steps = [
        {"card_code": "salary", "amount": 150000, "frequency": 1, "context": {"channel": "bank", "has_documents": True}, "action_details": {"employer_profile": "verified_employer", "income_basis": "payroll_registry"}},
        {"card_code": "card_transfer", "amount": 100000, "frequency": 2, "context": {"channel": "mobile", "has_documents": True}, "action_details": {"transfer_purpose": "family_support", "recipient_relationship": "family"}},
    ]
    p1_put_res2 = client.put(f"/api/v1/rounds/{round_id}/scenario", json={"expected_revision": p1_rev, "steps": p1_valid_steps}, headers=p1_headers)
    assert p1_put_res2.status_code == 200
    p1_rev2 = p1_put_res2.json()["revision"]

    # Submit succeeds
    p1_sub_ok = client.post(f"/api/v1/rounds/{round_id}/scenario/submit", json={"expected_revision": p1_rev2}, headers=p1_headers)
    assert p1_sub_ok.status_code == 200
    assert p1_sub_ok.json()["status"] == "submitted"

    # 9. Participant 2 submits a multi-channel evasion sequence
    p2_steps = [
        {"card_code": "salary", "amount": 100000, "frequency": 1, "context": {"channel": "bank", "has_documents": True}, "action_details": {"employer_profile": "verified_employer", "income_basis": "payroll_registry"}},
        {"card_code": "cash_deposit", "amount": 50000, "frequency": 1, "context": {"channel": "atm", "time_of_day": "evening", "velocity": "rapid", "has_documents": True}, "action_details": {"funds_source": "unexplained", "deposit_pattern": "single_location"}},
        {"card_code": "crypto_exchange", "amount": 60000, "frequency": 1, "context": {"channel": "exchange", "country_risk": "medium", "recipient_type": "new_counterparty", "time_of_day": "day", "velocity": "normal", "has_documents": True}, "action_details": {"platform_profile": "licensed_exchange", "wallet_owner": "own_wallet", "asset_profile": "privacy_asset"}},
        {"card_code": "international", "amount": 40000, "frequency": 1, "context": {"channel": "web", "country_risk": "high", "recipient_type": "known_counterparty", "time_of_day": "evening", "velocity": "normal", "has_documents": True}, "action_details": {"transfer_purpose": "investment", "payment_route": "fintech_gateway"}},
        {"card_code": "card_transfer", "amount": 100000, "frequency": 1, "context": {"channel": "mobile", "country_risk": "low", "recipient_type": "new_counterparty", "time_of_day": "day", "velocity": "normal", "has_documents": True}, "action_details": {"transfer_purpose": "family_support", "recipient_relationship": "acquaintance"}},
    ]
    p2_put = client.put(f"/api/v1/rounds/{round_id}/scenario", json={"expected_revision": 0, "steps": p2_steps}, headers=p2_headers)
    assert p2_put.status_code == 200
    p2_sub = client.post(f"/api/v1/rounds/{round_id}/scenario/submit", json={"expected_revision": p2_put.json()["revision"]}, headers=p2_headers)
    assert p2_sub.status_code == 200

    # 10. Participant 3 only creates draft
    p3_steps = [
        {"card_code": "salary", "amount": 50000, "frequency": 1, "context": {"channel": "bank", "has_documents": True}},
    ]
    p3_put = client.put(f"/api/v1/rounds/{round_id}/scenario", json={"expected_revision": 0, "steps": p3_steps}, headers=p3_headers)
    assert p3_put.status_code == 200

    # 11. Admin verifies real-time round stats
    stats_res = client.get(f"/api/v1/admin/rounds/{round_id}/stats", headers=admin_headers)
    assert stats_res.status_code == 200
    st_data = stats_res.json()
    assert st_data["submitted_scenarios"] == 2
    assert st_data["draft_scenarios"] == 1

    # 12. Admin checks participant details and blocks Bob (P2)
    p2_detail = client.get(f"/api/v1/admin/rounds/{round_id}/participants/{p2_user_id}", headers=admin_headers)
    assert p2_detail.status_code == 200
    p2_access_rev = p2_detail.json()["user"]["access_revision"]

    block_res = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{p2_user_id}/access",
        json={"blocked": True, "reason": "Тестовая блокировка организатором", "expected_access_revision": p2_access_rev},
        headers=admin_headers,
    )
    assert block_res.status_code == 200
    assert block_res.json()["is_blocked"] is True

    # Check that Bob's session is revoked
    bob_check = client.get(f"/api/v1/rounds/{round_id}/scenario", headers=p2_headers)
    assert bob_check.status_code in [401, 403]

    # Admin unblocks Bob
    unblock_res = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{p2_user_id}/access",
        json={"blocked": False, "reason": "Разблокирован после разъяснения", "expected_access_revision": block_res.json().get("access_revision", p2_access_rev + 1)},
        headers=admin_headers,
    )
    assert unblock_res.status_code == 200

    # Bob re-logins
    bob_relogin = client.post("/api/v1/auth/login", json={"email": "bob@aml.local", "password": "password123", "audience": "play"})
    assert bob_relogin.status_code == 200
    p2_headers = {"X-Session-ID": bob_relogin.json()["session_id"]}

    # 13. Admin triggers scoring
    score_res = client.post(f"/api/v1/admin/rounds/{round_id}/score", headers=admin_headers)
    assert score_res.status_code == 200
    score_out = score_res.json()
    assert score_out["status"] == "completed"
    assert score_out["scored_count"] == 2
    assert score_out["excluded_draft_count"] == 1

    # 14. Participant 1 checks results
    p1_result = client.get(f"/api/v1/rounds/{round_id}/result", headers=p1_headers)
    assert p1_result.status_code == 200
    p1_res_data = p1_result.json()
    assert p1_res_data["base"]["risk_label"] == "normal"
    assert "catboost_features_payload" in p1_res_data["explanation"]
    assert p1_res_data["explanation"]["catboost_features_payload"]["total_outflow"] == 200000.0

    # Participant 2 checks results (should have high risk / review or suspicious)
    p2_result = client.get(f"/api/v1/rounds/{round_id}/result", headers=p2_headers)
    assert p2_result.status_code == 200
    p2_res_data = p2_result.json()
    assert float(p2_res_data["base"]["risk_score"]) > float(p1_res_data["base"]["risk_score"])

    # 15. Admin applies leaderboard adjustment to Participant 1
    p1_user_id = p1_login.json()["user"]["id"]
    adj_res = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{p1_user_id}/leaderboard-adjustment",
        json={"expected_revision": 0, "reason": "Бонус за образцовый зарплатный профиль", "game_score_override": "98.50"},
        headers=admin_headers,
    )
    assert adj_res.status_code == 200

    # 16. Verify updated leaderboard reflects adjustment
    lb_res = client.get(f"/api/v1/rounds/{round_id}/leaderboard", headers=p1_headers)
    assert lb_res.status_code == 200
    lb_rows = lb_res.json()["rows"]
    assert len(lb_rows) == 2
    assert lb_rows[0]["display_name"] == "Alice Fin"
    assert float(lb_rows[0]["game_score"]) == 98.5

    # 17. Verify Audit Trail contains events
    audit_res = client.get(f"/api/v1/admin/rounds/{round_id}/audit-events", headers=admin_headers)
    assert audit_res.status_code == 200
    events = audit_res.json()["rows"]
    assert len(events) >= 4
    event_types = [e["event_type"] for e in events]
    assert "round_created" in event_types
    assert "round_activated" in event_types
    assert "round_scored" in event_types
    assert "leaderboard_adjusted" in event_types
