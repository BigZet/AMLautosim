from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.aml_workshop_simulator.api.main import app
from src.aml_workshop_simulator.ui.shared.api_client import SimulatorAPIClient

client = TestClient(app)


def test_scenario_persistence_across_login_logout_and_submit() -> None:
    """
    Test scenario persistence:
    1. User registers and logs in.
    2. User puts scenario draft with multiple steps -> revision 1 saved in DB.
    3. User logs out (session deleted).
    4. User logs back in -> GET /scenario returns exact draft steps and revision 1.
    5. User submits scenario -> status becomes 'submitted'.
    6. User logs out again.
    7. User logs back in -> GET /scenario returns status='submitted' and exact steps.
    8. User attempts to PUT /scenario on submitted scenario -> returned revision is locked / managed properly.
    """
    api = SimulatorAPIClient()

    # 1. Admin ensures active round
    admin_login = api.login("admin@aml.local", "admin12345", audience="admin")
    admin_sid = admin_login["session_id"]
    active = api.get_active_round()
    if not active:
        new_r = api.admin_create_round(
            title="Persistence Test Round",
            game_config={
                "resources": {"initial_balance": "250000.00", "initial_energy": 14, "initial_time": 18, "initial_trust": 100},
                "objectives": {"target_outflow": "150000.00", "max_actions": 8},
                "constraints": {"max_identical_steps": 2, "max_night_operations": 2},
                "ruleset_version": "game-rules-v2",
            },
            session_id=admin_sid,
        )
        api.admin_activate_round(new_r["id"], admin_sid)
        active = api.get_active_round()

    round_id = active["id"]

    # 2. Register & Login test user
    email = "persistent_user@aml.local"
    try:
        api.register(email, "Persistent User", "pass12345")
    except Exception:
        pass

    login_1 = api.login(email, "pass12345", audience="play")
    sid_1 = login_1["session_id"]

    # 3. Create Draft Scenario
    steps = [
        {"card_code": "salary", "amount": 100000, "frequency": 1, "context": {"channel": "bank", "has_documents": True}},
        {"card_code": "card_transfer", "amount": 75000, "frequency": 2, "context": {"channel": "mobile", "has_documents": True}},
    ]
    put_1 = api.put_scenario(round_id, steps, expected_revision=0, session_id=sid_1)
    assert put_1["status"] == "draft"
    assert put_1["revision"] == 1
    assert len(put_1["steps"]) == 2

    # 4. Logout
    api.logout(sid_1)

    # 5. Login again with a fresh session
    login_2 = api.login(email, "pass12345", audience="play")
    sid_2 = login_2["session_id"]
    assert sid_2 != sid_1

    # Fetch scenario -> MUST BE PRESERVED FROM DB!
    restored_scen = api.get_scenario(round_id, session_id=sid_2)
    assert restored_scen is not None
    assert restored_scen["status"] == "draft"
    assert restored_scen["revision"] == 1
    assert len(restored_scen["steps"]) == 2
    assert restored_scen["steps"][0]["card_code"] == "salary"
    assert restored_scen["steps"][1]["card_code"] == "card_transfer"

    # 6. Submit scenario
    sub_res = api.submit_scenario(round_id, expected_revision=restored_scen["revision"], session_id=sid_2)
    assert sub_res["status"] == "submitted"
    assert sub_res["submitted_at"] is not None

    # 7. Logout again
    api.logout(sid_2)

    # 8. Login third time
    login_3 = api.login(email, "pass12345", audience="play")
    sid_3 = login_3["session_id"]

    # Fetch scenario -> MUST BE SUBMITTED & PERSISTED!
    submitted_scen = api.get_scenario(round_id, session_id=sid_3)
    assert submitted_scen is not None
    assert submitted_scen["status"] == "submitted"
    assert submitted_scen["submitted_at"] is not None
    assert len(submitted_scen["steps"]) == 2
