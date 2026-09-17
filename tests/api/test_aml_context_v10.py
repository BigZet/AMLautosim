"""Public v10 context and evidence choices, using an isolated PostgreSQL round."""

import json
from copy import deepcopy

from tests.aml_context_support import context_fixture
from src.aml_workshop_simulator.services.round_configuration import config_version


def install_context(sql, round_id):
    config, steps = context_fixture()
    config["config_version"] = config_version(config)
    # Test-only round: normal creation/start is still release-gated.
    sql("UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id", {
        "config": json.dumps(config), "id": round_id,
    })
    return config, steps


def test_all_players_see_same_context_and_claims_survive_save_reload_submit(
    request_api, admin, player, player_factory, active_round, sql, command,
):
    config, steps = install_context(sql, active_round)
    second = player_factory()
    contexts = []
    for headers in (player["headers"], second["headers"]):
        state = request_api("GET", "/rounds/current/state", headers)
        contexts.append(state["round"]["game_config"]["behavior"]["aml_context"])
    assert contexts[0] == contexts[1] == config["behavior"]["aml_context"]
    assert "author_truth" not in json.dumps(contexts)
    assert "reviewer" not in json.dumps(contexts)
    path = f"/rounds/{active_round}/scenario"
    # A known claim selected for the wrong party is retained as a mismatch.
    steps[0]["sender_id"] = "B"
    preview = request_api("POST", path + "/preview", player["headers"], {"steps": steps})
    assert preview["can_submit"] and "risk_score" not in preview
    saved = request_api("PUT", path, player["headers"], command(steps))
    loaded = request_api("GET", path, player["headers"])
    assert loaded["steps"] == saved["steps"]
    assert loaded["steps"][0]["claim_id"] == "shared"
    assert loaded["steps"][0]["purpose_code"] == "shared_expense"
    submitted = request_api("POST", path + "/submit", player["headers"], command(steps, saved["revision"]))
    assert submitted["status"] == "submitted"
    state = request_api("GET", "/rounds/current/state", second["headers"])
    assert state["round"]["game_config"]["behavior"]["aml_context"] == contexts[0]


def test_forged_evidence_is_rejected_and_cannot_mutate_round(
    request_api, admin, player, active_round, sql, command,
):
    config, steps = install_context(sql, active_round)
    path = f"/rounds/{active_round}/scenario"
    for field, value in (("verification_status", "verified"), ("provenance", "independent_record"), ("fact", {"id":"forged"}), ("claim_id", "forged")):
        forged = deepcopy(steps)
        forged[0][field] = value
        request_api("PUT", path, player["headers"], command(forged), status=422)
    state = request_api("GET", "/rounds/current/state", player["headers"])
    assert state["scenario"] is None
    assert state["round"]["game_config"]["behavior"]["aml_context"] == config["behavior"]["aml_context"]
    attempted = deepcopy(config)
    for key in ("card_snapshots", "config_version", "risk_model"):
        attempted.pop(key, None)
    attempted["behavior"]["aml_context"]["facts"][0]["verification_status"] = "contradicted"
    request_api("PUT", f"/admin/rounds/{active_round}", admin, {
        "expected_config_revision": 1, "game_config": attempted,
    }, status=409)
    after = request_api("GET", "/rounds/current/state", player["headers"])
    assert after["round"]["game_config"]["behavior"]["aml_context"] == config["behavior"]["aml_context"]
    sql("UPDATE rounds SET status='draft' WHERE id=:id", {"id": active_round})
    error = request_api("POST", f"/admin/rounds/{active_round}/start", admin, status=409)
    assert error["code"] == "model_contract_mismatch"
