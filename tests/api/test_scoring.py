
import pytest
from src.aml_workshop_simulator.services import scoring_run


def test_ranking_ties_access_and_shared_results(
    request_api, admin, player_factory, active_round, chain, command
):
    players = [player_factory(f"Участник {n}") for n in range(2)]
    payloads = [command(chain()) for _ in players]
    for player, payload in zip(players, payloads):
        request_api(
            "POST",
            f"/rounds/{active_round}/scenario/submit",
            player["headers"],
            payload,
        )
    board_path = f"/rounds/{active_round}/leaderboard"
    assert request_api("GET", board_path, players[0]["headers"])["rows"] == []
    summary = request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin)
    assert summary["scored_count"] == 2
    assert request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin) == summary
    rows = request_api("GET", board_path, players[0]["headers"])["rows"]
    assert [r["rank"] for r in rows] == [1, 1]
    assert {r["display_name"] for r in rows} == {p["display_name"] for p in players}
    assert all("masked" not in r and "email" not in r for r in rows)
    for player, payload in zip(players, payloads):
        h = player["headers"]
        state = request_api("GET", "/rounds/current/state", h)
        assert state["result"]["rank"] == 1 and state["can_view_leaderboard"]
        assert state["scenario"] == request_api(
            "GET", f"/rounds/{active_round}/scenario", h
        )
        assert state["result"] == request_api(
            "GET", f"/rounds/{active_round}/result", h
        )
        assert (
            request_api("POST", f"/rounds/{active_round}/scenario/submit", h, payload)[
                "status"
            ]
            == "scored"
        )
    access = f"/admin/rounds/{active_round}/participants/{players[0]['id']}/access"
    request_api(
        "PUT",
        access,
        admin,
        dict(blocked=True, reason="Проверка блокировки", expected_access_revision=1),
    )
    request_api("GET", "/auth/session", players[0]["headers"], status=401)
    public = request_api("GET", board_path, players[1]["headers"])["rows"]
    private = request_api("GET", f"/admin/rounds/{active_round}/leaderboard", admin)[
        "rows"
    ]
    assert len(public) == 1 and public[0]["rank"] == 1
    assert [r["rank"] for r in private if not r["is_blocked"]] == [
        r["rank"] for r in public
    ]
    assert next(r for r in private if r["is_blocked"])["rank"] is None
    request_api(
        "PUT",
        access,
        admin,
        dict(
            blocked=False, reason="Проверка разблокировки", expected_access_revision=1
        ),
        409,
    )
    request_api(
        "PUT",
        access,
        admin,
        dict(
            blocked=False, reason="Проверка разблокировки", expected_access_revision=2
        ),
    )
    request_api("GET", "/auth/session", players[0]["headers"], status=401)


def test_scoring_failure_rolls_back_scores_but_keeps_cutoff(
    request_api, admin, player, active_round, chain, command, monkeypatch, sql
):
    request_api(
        "POST",
        f"/rounds/{active_round}/scenario/submit",
        player["headers"],
        command(chain()),
    )
    original = scoring_run.score_round

    async def fail_after_writes(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("Injected failure after scoring writes")

    monkeypatch.setattr(scoring_run, "score_round", fail_after_writes)
    error = request_api(
        "POST", f"/admin/rounds/{active_round}/score?wait=true", admin, status=500
    )
    assert error["code"] == "scoring_failed"
    state = request_api("GET", "/rounds/current/state", player["headers"])
    assert state["round"]["status"] == "closed" and state["result"] is None
    assert state["scenario"]["status"] == "submitted"
    assert not state["can_edit"] and not state["can_view_leaderboard"]
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0
    request_api(
        "PUT",
        f"/rounds/{active_round}/scenario",
        player["headers"],
        command(chain(), 1),
        409,
    )
    monkeypatch.setattr(scoring_run, "score_round", original)
    assert (
        request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin)[
            "scored_count"
        ]
        == 1
    )


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
