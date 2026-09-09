"""Exercise real database locks using concurrent HTTP requests."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from sqlalchemy import event

from src.aml_workshop_simulator.db.session import async_engine
from src.aml_workshop_simulator.services import scoring_run


def test_submission_races_autosave(
    api, request_api, player, active_round, chain, command
):
    barrier = Barrier(2)
    path = f"/api/v1/rounds/{active_round}/scenario"

    def send(method, suffix):
        barrier.wait(timeout=10)
        return api.request(
            method, path + suffix, headers=player["headers"], json=command(chain())
        )

    with ThreadPoolExecutor(2) as pool:
        submit = pool.submit(send, "POST", "/submit")
        save = pool.submit(send, "PUT", "")
        results = [submit.result(timeout=15), save.result(timeout=15)]
    assert sorted(r.status_code for r in results) == [200, 409]
    stored = request_api("GET", f"/rounds/{active_round}/scenario", player["headers"])
    assert stored["revision"] == 1
    assert stored["status"] == (
        "submitted" if results[0].status_code == 200 else "editing"
    )


def test_submission_races_cutoff(
    api, request_api, admin, player, active_round, chain, command
):
    barrier = Barrier(2)
    payload = command(chain())

    def submit():
        barrier.wait(timeout=10)
        return api.post(
            f"/api/v1/rounds/{active_round}/scenario/submit",
            headers=player["headers"],
            json=payload,
        )

    def score():
        barrier.wait(timeout=10)
        return api.post(f"/api/v1/admin/rounds/{active_round}/score", headers=admin)

    with ThreadPoolExecutor(2) as pool:
        submitted, scored = pool.submit(submit), pool.submit(score)
        sr, cr = submitted.result(timeout=15), scored.result(timeout=15)
    assert sr.status_code in (200, 409), sr.text
    assert cr.status_code == 200, cr.text
    state = request_api("GET", "/rounds/current/state", player["headers"])
    assert state["round"]["status"] == "completed"
    assert (state["result"] is not None) == (sr.status_code == 200)
    assert cr.json()["scored_count"] == int(sr.status_code == 200)


def test_state_is_one_nonblocking_snapshot_during_scoring(
    request_api, admin, player, active_round, chain, command, monkeypatch
):
    request_api(
        "POST",
        f"/rounds/{active_round}/scenario/submit",
        player["headers"],
        command(chain()),
    )
    started, release = Event(), Event()
    original = scoring_run.score_round

    async def gated(*args, **kwargs):
        started.set()
        if not await asyncio.to_thread(release.wait, 15):
            raise TimeoutError("Test did not release scoring")
        return await original(*args, **kwargs)

    monkeypatch.setattr(scoring_run, "score_round", gated)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with ThreadPoolExecutor(2) as pool:
        score = pool.submit(
            request_api, "POST", f"/admin/rounds/{active_round}/score", admin
        )
        try:
            assert started.wait(10)
            event.listen(async_engine.sync_engine, "before_cursor_execute", record)
            try:
                state = pool.submit(
                    request_api, "GET", "/rounds/current/state", player["headers"]
                ).result(timeout=3)
            finally:
                event.remove(async_engine.sync_engine, "before_cursor_execute", record)
            assert state["round"]["status"] == "scoring" and state["result"] is None
            assert state["scenario"]["status"] == "submitted"
            assert not state["can_edit"] and not state["can_view_leaderboard"]
            assert sum("FROM rounds" in s for s in statements) == 1
            assert all(
                "FOR UPDATE" not in s and "FOR SHARE" not in s for s in statements
            )
        finally:
            release.set()
        assert score.result(timeout=10)["scored_count"] == 1


def test_concurrent_submit_retries_record_once(
    api, request_api, player, active_round, chain, command, sql
):
    barrier = Barrier(2)
    payload = command(chain())

    def submit():
        barrier.wait(timeout=10)
        return api.post(
            f"/api/v1/rounds/{active_round}/scenario/submit",
            headers=player["headers"],
            json=payload,
        )

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(submit), pool.submit(submit)
        a, b = first.result(timeout=15), second.result(timeout=15)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert (
        sql(
            "SELECT count(*) AS n FROM audit_events WHERE event_type='scenario_submitted'"
        )[0]["n"]
        == 1
    )


def test_concurrent_scorers_publish_once(
    api, request_api, admin, player, active_round, chain, command, sql
):
    request_api(
        "POST",
        f"/rounds/{active_round}/scenario/submit",
        player["headers"],
        command(chain()),
    )
    barrier = Barrier(2)

    def score():
        barrier.wait(timeout=10)
        return api.post(f"/api/v1/admin/rounds/{active_round}/score", headers=admin)

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(score), pool.submit(score)
        a, b = first.result(timeout=15), second.result(timeout=15)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 1
