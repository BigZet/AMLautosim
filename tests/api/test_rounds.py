import pytest


@pytest.fixture
def seeded_game_version():
    return 10


def test_no_game_and_creation(request_api, player, admin, sql):
    sql("TRUNCATE rounds CASCADE")
    assert request_api("GET", "/rounds/current", player["headers"]) is None
    assert request_api("GET", "/rounds/current/state", player["headers"]) == dict(
        round=None,
        scenario=None,
        result=None,
        can_edit=False,
        can_submit=False,
        can_view_leaderboard=False,
    )
    created = request_api("POST", "/admin/rounds", admin, {"title": "Новая игра"}, 201)
    assert created["status"] == "draft"
    request_api("POST", "/admin/rounds", admin, {"title": "Дубликат"}, 409)


def test_configuration_only_before_start(
    request_api, admin, player, round_id, chain, command
):
    path = f"/admin/rounds/{round_id}"
    state = request_api("GET", "/rounds/current/state", player["headers"])
    assert state["round"]["status"] == "draft" and not state["can_edit"]
    request_api(
        "POST",
        f"/rounds/{round_id}/scenario/submit",
        player["headers"],
        command(chain()),
        409,
    )
    request_api("POST", path + "/score?wait=true", admin, status=409)
    updated = request_api(
        "PUT", path, admin, {"expected_config_revision": 1, "title": "Изменено"}
    )
    assert updated["config_revision"] == 2 and updated["title"] == "Изменено"
    request_api(
        "PUT", path, admin, {"expected_config_revision": 1, "title": "Устарело"}, 409
    )
    started = request_api("POST", path + "/start", admin)
    assert request_api("POST", path + "/start", admin) == started
    request_api(
        "PUT", path, admin, {"expected_config_revision": 2, "title": "Поздно"}, 409
    )


def test_restart_clears_game_preserves_accounts(
    request_api, admin, player, active_round, chain, command, sql
):
    h = player["headers"]
    request_api("POST", f"/rounds/{active_round}/scenario/submit", h, command(chain()))
    request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin)
    fresh = request_api(
        "POST", f"/admin/rounds/{active_round}/restart", admin, status=201
    )
    assert fresh["id"] != active_round and fresh["status"] == "draft"
    state = request_api("GET", "/rounds/current/state", h)
    assert (
        state["round"]["id"] == fresh["id"]
        and state["scenario"] is None
        and state["result"] is None
    )
    for suffix in ("scenario", "result", "cards", "leaderboard"):
        request_api("GET", f"/rounds/{active_round}/{suffix}", h, status=404)
    assert request_api("GET", "/auth/session", h)["id"] == player["id"]
    assert sql("SELECT count(*) AS n FROM scenarios")[0]["n"] == 0
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0
    assert {r["round_id"] for r in sql("SELECT round_id FROM audit_events")} == {
        None, fresh["id"]
    }


def test_unsent_chain_hidden_from_admin_and_deleted_at_cutoff(
    request_api, admin, player, active_round, chain, command, sql
):
    path = f"/rounds/{active_round}/scenario"
    request_api("PUT", path, player["headers"], command(chain(1)))
    detail = request_api(
        "GET", f"/admin/rounds/{active_round}/participants/{player['id']}", admin
    )
    assert detail["scenario"] is None
    request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin)
    state = request_api("GET", "/rounds/current/state", player["headers"])
    assert state["scenario"] is None and state["result"] is None
    assert (
        state["can_view_leaderboard"]
        and not state["can_edit"]
        and not state["can_submit"]
    )
    request_api("POST", path + "/submit", player["headers"], command(chain()), 409)
    assert sql("SELECT count(*) AS n FROM scenarios")[0]["n"] == 0


def test_organizer_energy_change_is_saved_with_revision(request_api, admin, round_id):
    before = request_api("GET", "/admin/rounds/current", admin)
    config = request_api("GET", "/admin/game-config/default", admin)
    config["resources"]["initial_energy"] = 1
    updated = request_api("PUT", f"/admin/rounds/{round_id}", admin,
                          {"expected_config_revision": before["config_revision"], "game_config": config})
    assert updated["config_revision"] == before["config_revision"] + 1
    assert updated["game_config"]["resources"]["initial_energy"] == 1
    current = request_api("GET", "/admin/rounds/current", admin)
    # The current-round read adds live admission/publication metadata (T08).
    live_fields = {"admission_counts", "results_version"}
    assert {k: v for k, v in current.items() if k not in live_fields} == {
        k: v for k, v in updated.items() if k not in live_fields
    }
    assert current["admission_counts"] is not None


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
