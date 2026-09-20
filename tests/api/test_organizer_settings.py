"""Organizer draft settings flow through validation, submission and scoring."""
import json
from copy import deepcopy
from pathlib import Path
import pytest

@pytest.fixture
def seeded_game_version():
    return 10


def test_draft_settings_and_scoring(request_api, admin, round_id, player_factory, command):
    current = request_api("GET", "/admin/rounds/current", admin)
    config = {k: deepcopy(v) for k,v in current["game_config"].items() if k not in {"risk_model","config_version","card_snapshots"}}
    config["resources"]["initial_balance"] = "500000.00"
    config["objectives"]["target_outflow"] = "100.00"
    config["constraints"]["max_identical_steps"] = 8
    config["behavior"]["history"]["operations"][0]["amount"] = "12345.67"
    config["behavior"]["purchases"].update(version="purchase-policy-v2", max_total="45000.00")
    for op in config["operations"]:
        if op["code"] == "purchase":
            op.update(min_amount="500.00", max_amount="40000.00", max_occurrences=5)
    body = {"game_config":config, "expected_config_revision":current["config_revision"]}
    player = player_factory("custom-settings")
    request_api("PUT", f"/admin/rounds/{round_id}", player["headers"], body, status=403)
    saved = request_api("PUT", f"/admin/rounds/{round_id}", admin, body)
    assert saved["game_config"]["behavior"]["purchases"]["max_total"] == "45000.00"
    request_api("POST", f"/admin/rounds/{round_id}/start", admin)
    body["expected_config_revision"] = saved["config_revision"]
    request_api("PUT", f"/admin/rounds/{round_id}", admin, body, status=409)
    baseline = json.loads((Path(__file__).parents[1]/"fixtures/retired_limits_baseline.json").read_text())["rows"][0]
    steps = deepcopy(baseline["steps"])
    ids = {(c["code"],c["version"]):c["id"] for c in saved["game_config"]["card_snapshots"]}
    for step in steps:
        step["card"]["id"] = ids[(step["card"]["code"],step["card"]["version"])]
    request_api("POST", f"/rounds/{round_id}/scenario/submit", player["headers"], command(steps))
    request_api("POST", f"/admin/rounds/{round_id}/score", admin)
    result = request_api("GET", "/rounds/current/state", player["headers"])["result"]
    assert result["explanation"]["aml_probability"] == baseline["probability"]
