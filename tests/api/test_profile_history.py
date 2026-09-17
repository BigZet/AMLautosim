from copy import deepcopy

from tests.profile_history_support import profile_config
from tests.purchase_support import mixed_goal


def test_draft_freeze_two_players_reload_and_immutable_after_start(
    monkeypatch, request_api, admin, round_id, player_factory, command, sql
):
    config = request_api("GET", "/admin/game-config/default?schema_version=8", admin)
    history_config = profile_config()
    for key in ("counterparties", "profile", "history", "timeline"):
        config["behavior"][key] = history_config["behavior"][key]
    saved = request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {
            "expected_config_revision": 1,
            "game_config": config,
        },
    )
    assert saved["context_summary"]["activity"]["inflow"] == "105000.50"
    frozen = sql("SELECT game_config FROM rounds")[0]["game_config"]
    assert (
        "context_summary" not in frozen
        and "activity" not in frozen["behavior"]["history"]
    )
    assert frozen["behavior"]["history"]["version"] == "observed-history-v1"
    request_api("POST", f"/admin/rounds/{round_id}/start", admin)
    first, second = player_factory("Первый"), player_factory("Второй")

    def read(player):
        return request_api("GET", "/rounds/current/state", player["headers"])

    one, two = read(first), read(second)
    assert one["round"] == two["round"]
    assert one["round"]["context_summary"] == saved["context_summary"]
    path = f"/rounds/{round_id}/scenario"
    empty = request_api("POST", path + "/preview", first["headers"], {"steps": []})
    assert empty["resources"]["totals"]["target_outflow"] == "0.00"
    assert empty["resources"]["resources_after"]["balance"] == "180000.00"
    values = mixed_goal(frozen)
    result = request_api("PUT", path, first["headers"], command(values))
    assert result["resources"]["totals"]["target_outflow"] == "400000.00"
    assert read(first)["round"] == read(second)["round"] == one["round"]
    changed = deepcopy(config)
    changed["behavior"]["profile"]["title"] = "Другой профиль"
    request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {
            "expected_config_revision": 2,
            "game_config": changed,
        },
        409,
    )
    request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        first["headers"],
        {
            "expected_config_revision": 2,
            "game_config": changed,
        },
        403,
    )
    assert sql("SELECT game_config FROM rounds")[0]["game_config"] == frozen


def test_invalid_history_rejected_before_save_and_gate_stays_closed(
    request_api, admin, round_id, sql
):
    config = profile_config()
    config.pop("card_snapshots")
    original = sql("SELECT game_config FROM rounds")[0]["game_config"]
    payload = {"expected_config_revision": 1, "game_config": config}
    request_api("PUT", f"/admin/rounds/{round_id}", admin, payload, 409)
    config["behavior"]["history"]["operations"][0]["occurred_at"] = config["behavior"][
        "timeline"
    ]["starts_at"]
    request_api("PUT", f"/admin/rounds/{round_id}", admin, payload, 422)
    assert sql("SELECT game_config FROM rounds")[0]["game_config"] == original
