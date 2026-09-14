from copy import deepcopy

from scripts.check_expanded_balance import demo_steps
from src.aml_workshop_simulator.core.config import settings


def test_released_round_full_cycle_and_emergency_creation_switch(
    monkeypatch, request_api, admin, round_id, player_factory, command, sql
):
    monkeypatch.setattr(settings, "EXPANDED_ROUNDS_ENABLED", True)
    metadata = request_api("GET", "/admin/game-config/editor-metadata", admin)
    assert metadata["available_contracts"] == [8]
    new = request_api(
        "POST", f"/admin/rounds/{round_id}/restart?schema_version=8", admin, status=201
    )
    identity = new["id"]
    assert identity != round_id and new["game_config"]["schema_version"] == 8
    assert new["context_summary"]["status"] == "observed"
    config = new["game_config"]
    frozen = deepcopy(sql("SELECT game_config FROM rounds")[0]["game_config"])
    downgraded = deepcopy(config)
    downgraded.pop("card_snapshots")
    downgraded.pop("risk_model", None)
    downgraded.pop("config_version")
    downgraded["behavior"].pop("release")
    request_api(
        "PUT",
        f"/admin/rounds/{identity}",
        admin,
        {"expected_config_revision": 1, "game_config": downgraded},
        409,
    )
    request_api("POST", f"/admin/rounds/{identity}/start", admin)
    monkeypatch.setattr(settings, "EXPANDED_ROUNDS_ENABLED", False)
    assert (
        request_api("GET", "/admin/game-config/editor-metadata", admin)[
            "available_contracts"
        ]
        == []
    )
    request_api(
        "POST", f"/admin/rounds/{identity}/restart?schema_version=8", admin, status=409
    )
    assert sql("SELECT game_config FROM rounds")[0]["game_config"] == frozen
    players = []
    for variant in ("baseline", "purchase", "varied"):
        player = player_factory(variant)
        players.append(player)
        values = demo_steps(config, variant)
        values[1], values[2] = values[2], values[1]
        state = request_api("GET", "/rounds/current/state", player["headers"])
        assert state["can_edit"] and state["round"]["accepts_changes"]
        assert state["round"]["context_summary"] == new["context_summary"]
        path = f"/rounds/{identity}/scenario"
        preview = request_api(
            "POST", path + "/preview", player["headers"], {"steps": values}
        )
        assert preview["can_submit"]
        packet = command(values)
        saved = request_api("PUT", path, player["headers"], packet)
        assert request_api("PUT", path, player["headers"], packet) == saved
        request_api("PUT", path, player["headers"], command(values), 409)
        assert request_api("GET", path, player["headers"])["steps"] == saved["steps"]
        submitted = request_api(
            "POST", path + "/submit", player["headers"], command(values, 1)
        )
        assert submitted["resources"] == preview["resources"]
    request_api("POST", f"/admin/rounds/{identity}/score", admin)
    for player in players:
        result = request_api("GET", "/rounds/current/state", player["headers"])
        assert result["result"]["rank"] in (1, 2, 3)
        assert result["result"]["resources"]["totals"]["target_outflow"] == "400000.00"
        assert result["round"]["context_summary"] == new["context_summary"]
        board = request_api("GET", f"/rounds/{identity}/leaderboard", player["headers"])
        own = next(row for row in board["rows"] if row["is_current_user"])
        assert own["rank"] == result["result"]["rank"]
        assert own["game_score"] == result["result"]["scores"]["game_score"]
    assert sql("SELECT game_config FROM rounds")[0]["game_config"] == frozen


def test_no_in_place_upgrade_and_disabled_default(
    monkeypatch, request_api, admin, round_id
):
    monkeypatch.setattr(settings, "EXPANDED_ROUNDS_ENABLED", False)
    request_api("GET", "/admin/game-config/default?schema_version=8", admin, status=409)
    monkeypatch.setattr(settings, "EXPANDED_ROUNDS_ENABLED", True)
    from src.aml_workshop_simulator.core.game_config import base_game_config

    config = base_game_config()
    request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {"game_config": config, "expected_config_revision": 1},
        409,
    )
    assert len(request_api("GET", "/admin/action-cards?schema_version=8", admin)) == 5
    assert len(request_api("GET", "/admin/action-cards", admin)) == 5


def test_employer_incoming_is_rejected_by_api(
    request_api, admin, round_id, player_factory
):
    new = request_api(
        "POST", f"/admin/rounds/{round_id}/restart?schema_version=8", admin, status=201
    )
    assert new["game_config"]["behavior"]["sender_policy"] == "separate-employer-v1"
    request_api("POST", f"/admin/rounds/{new['id']}/start", admin)
    player = player_factory("sender-policy")
    values = demo_steps(new["game_config"])
    values[0]["sender_id"] = "employer"
    request_api(
        "POST",
        f"/rounds/{new['id']}/scenario/preview",
        player["headers"],
        {"steps": values},
        422,
    )
    values[0]["sender_id"] = "A"
    preview = request_api(
        "POST",
        f"/rounds/{new['id']}/scenario/preview",
        player["headers"],
        {"steps": values},
    )
    assert preview["can_submit"]
