"""Durable admission, leases, crash recovery and atomic publication."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import time

import pytest

from src.aml_workshop_simulator.db.session import AsyncSessionLocal


@pytest.fixture(params=[10])
def seeded_game_version(request):
    return request.param


@pytest.fixture(autouse=True)
def serial_crash_points(monkeypatch):
    from src.aml_workshop_simulator.core.config import settings

    monkeypatch.setattr(settings, "SCORING_THREADS", 1)


def submit(request_api, player, round_id, chain, command):
    request_api(
        "POST",
        f"/rounds/{round_id}/scenario/submit",
        player["headers"],
        command(chain()),
    )


def enqueue(api, admin, round_id):
    response = api.post(f"/api/v1/admin/rounds/{round_id}/score", headers=admin)
    assert response.status_code == 202, response.text
    return response.json()


def state(request_api, admin, job):
    return request_api("GET", f"/admin/scoring-jobs/{job['job_id']}", admin)


def test_queued_job_survives_request_and_repeats_share_it(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    sql,
):
    submit(request_api, player, active_round, chain, command)
    job = enqueue(api, admin, active_round)
    assert (job["state"], job["done"], job["total"]) == ("queued", 0, 1)
    assert enqueue(api, admin, active_round)["job_id"] == job["job_id"]
    assert state(request_api, admin, job)["state"] == "queued"
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0
    from src.aml_workshop_simulator.services.scoring_jobs import run_one

    assert asyncio.run(run_one(AsyncSessionLocal))
    completed = state(request_api, admin, job)
    assert (completed["state"], completed["done"], completed["total"]) == (
        "completed",
        1,
        1,
    )
    assert completed["summary"]["scored_count"] == 1
    assert enqueue(api, admin, active_round)["job_id"] == job["job_id"]
    assert (
        request_api("GET", "/rounds/current/state", player["headers"])["result"]
        is not None
    )
    request_api(
        "GET", f"/admin/scoring-jobs/{job['job_id']}", player["headers"], status=403
    )


def test_concurrent_enqueue_creates_one_job(api, admin, active_round, sql):
    barrier = Barrier(2)

    def send():
        barrier.wait(timeout=10)
        return enqueue(api, admin, active_round)

    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(lambda _: send(), range(2)))
    assert jobs[0]["job_id"] == jobs[1]["job_id"]
    assert sql("SELECT count(*) AS n FROM scoring_jobs")[0]["n"] == 1


class WorkerCrash(BaseException):
    pass


@pytest.mark.parametrize("stage", ["after_claim", "midway", "before_publish"])
def test_crash_lease_recovery_never_publishes_partial_results(
    api,
    request_api,
    admin,
    player_factory,
    active_round,
    chain,
    command,
    sql,
    monkeypatch,
    stage,
):
    from src.aml_workshop_simulator.services import scoring_jobs

    for i in range(3):
        submit(request_api, player_factory(f"Crash {i}"), active_round, chain, command)
    job = enqueue(api, admin, active_round)
    original = scoring_jobs.calculate_step
    calls = 0

    def crashing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == (1 if stage == "after_claim" else 2):
            raise WorkerCrash()
        return original(*args, **kwargs)

    async def before_publish(*args, **kwargs):
        raise WorkerCrash()

    with monkeypatch.context() as patch:
        if stage == "before_publish":
            patch.setattr(scoring_jobs, "publish", before_publish)
        else:
            patch.setattr(scoring_jobs, "calculate_step", crashing)
        with pytest.raises(WorkerCrash):
            asyncio.run(scoring_jobs.run_one(AsyncSessionLocal))
    progress = state(request_api, admin, job)
    assert progress["state"] == "running"
    assert (
        progress["done"] == {"after_claim": 0, "midway": 1, "before_publish": 3}[stage]
    )
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0
    sql("UPDATE scoring_jobs SET lease_until = now() - interval '1 second'")
    assert asyncio.run(scoring_jobs.run_one(AsyncSessionLocal))
    completed = state(request_api, admin, job)
    assert completed["state"] == "completed" and completed["attempt"] == 2
    assert completed["done"] == completed["total"] == 3
    assert sql(
        "SELECT count(*) AS n, count(DISTINCT scenario_id) AS unique_n FROM scoring_results"
    )[0] == {"n": 3, "unique_n": 3}


def test_two_workers_claim_once(
    api, request_api, admin, player, active_round, chain, command
):
    from src.aml_workshop_simulator.services.scoring_jobs import run_one

    submit(request_api, player, active_round, chain, command)
    job = enqueue(api, admin, active_round)

    async def run():
        return await asyncio.gather(
            run_one(AsyncSessionLocal), run_one(AsyncSessionLocal)
        )

    assert sum(asyncio.run(run())) == 1
    assert state(request_api, admin, job)["attempt"] == 1


def test_restart_during_calculation_cancels_without_resurrection(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    sql,
    monkeypatch,
):
    from src.aml_workshop_simulator.services import scoring_jobs

    submit(request_api, player, active_round, chain, command)
    job = enqueue(api, admin, active_round)
    entered, release = Event(), Event()
    original = scoring_jobs.calculate_step

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(scoring_jobs, "calculate_step", delayed)
    with ThreadPoolExecutor(1) as pool:
        worker = pool.submit(asyncio.run, scoring_jobs.run_one(AsyncSessionLocal))
        try:
            assert entered.wait(10)
            started = time.monotonic()
            fresh = request_api(
                "POST", f"/admin/rounds/{active_round}/restart", admin, status=201
            )
            assert time.monotonic() - started < 3
        finally:
            release.set()
        worker.result(timeout=15)
    assert fresh["id"] != active_round
    assert state(request_api, admin, job)["state"] == "cancelled"
    assert sql("SELECT snapshot FROM scoring_jobs") == [{"snapshot": {}}]
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0
    assert sql("SELECT id, status FROM rounds") == [
        {"id": fresh["id"], "status": "draft"}
    ]


@pytest.mark.parametrize("changed", ["round", "scenario"])
def test_publication_rejects_changed_snapshot(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    sql,
    changed,
):
    from src.aml_workshop_simulator.services.scoring_jobs import run_one

    submit(request_api, player, active_round, chain, command)
    job = enqueue(api, admin, active_round)
    sql(
        "UPDATE rounds SET config_revision=config_revision+1"
        if changed == "round"
        else "UPDATE scenarios SET revision=revision+1"
    )
    asyncio.run(run_one(AsyncSessionLocal))
    failed = state(request_api, admin, job)
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "scoring_snapshot_changed"
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0


def test_queue_failure_keeps_cutoff_and_can_retry(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    monkeypatch,
    sql,
):
    from src.aml_workshop_simulator.services import scoring_jobs

    submit(request_api, player, active_round, chain, command)

    async def broken(*args, **kwargs):
        raise RuntimeError("private-path-must-not-leak")

    with monkeypatch.context() as patch:
        patch.setattr(scoring_jobs, "freeze_snapshot", broken)
        response = api.post(f"/api/v1/admin/rounds/{active_round}/score", headers=admin)
        assert response.status_code == 500
        assert "private-path" not in response.text
    assert sql("SELECT status FROM rounds") == [{"status": "closed"}]
    assert sql("SELECT count(*) AS n FROM scoring_jobs")[0]["n"] == 0
    job = enqueue(api, admin, active_round)
    assert asyncio.run(scoring_jobs.run_one(AsyncSessionLocal))
    assert state(request_api, admin, job)["state"] == "completed"


def test_expired_owner_cannot_renew_or_publish_after_reclaim(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    sql,
):
    from src.aml_workshop_simulator.services import scoring_jobs

    submit(request_api, player, active_round, chain, command)
    job = enqueue(api, admin, active_round)
    old = asyncio.run(scoring_jobs.claim(AsyncSessionLocal))
    sql("UPDATE scoring_jobs SET lease_until=now()-interval '1 second'")
    new = asyncio.run(scoring_jobs.claim(AsyncSessionLocal))
    assert old["id"] == new["id"] and old["owner"] != new["owner"]
    assert not asyncio.run(scoring_jobs.progress(AsyncSessionLocal, old, 1))
    assert not asyncio.run(scoring_jobs.publish(AsyncSessionLocal, old, [], 0))
    asyncio.run(scoring_jobs.execute_claimed(AsyncSessionLocal, new))
    completed = state(request_api, admin, job)
    assert completed["state"] == "completed" and completed["attempt"] == 2
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 1


def test_heartbeat_retains_lease_during_slow_cpu_work(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    monkeypatch,
):
    from src.aml_workshop_simulator.core.config import settings
    from src.aml_workshop_simulator.services import scoring_jobs

    monkeypatch.setattr(settings, "SCORING_LEASE_SECONDS", 5)
    submit(request_api, player, active_round, chain, command)
    job = enqueue(api, admin, active_round)
    entered, release = Event(), Event()
    original = scoring_jobs.calculate_step

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(scoring_jobs, "calculate_step", delayed)
    with ThreadPoolExecutor(1) as pool:
        worker = pool.submit(asyncio.run, scoring_jobs.run_one(AsyncSessionLocal))
        try:
            assert entered.wait(10)
            time.sleep(
                6
            )  # exceed original lease; heartbeat must renew via another session
            assert not asyncio.run(scoring_jobs.run_one(AsyncSessionLocal))
        finally:
            release.set()
        worker.result(timeout=15)
    completed = state(request_api, admin, job)
    assert completed["state"] == "completed" and completed["attempt"] == 1


def test_legacy_wait_response_uses_the_same_durable_job(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
    scoring_worker,
    sql,
):
    submit(request_api, player, active_round, chain, command)
    response = api.post(
        f"/api/v1/admin/rounds/{active_round}/score?wait=true", headers=admin
    )
    assert response.status_code == 200, response.text
    assert response.json()["scored_count"] == 1
    assert sql("SELECT state, done, total FROM scoring_jobs") == [
        {"state": "completed", "done": 1, "total": 1},
    ]


def test_progress_poll_does_not_load_frozen_scenario_payload(api, request_api, admin, active_round):
    from sqlalchemy import event
    from src.aml_workshop_simulator.db.session import async_engine
    job = enqueue(api, admin, active_round)
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(async_engine.sync_engine, 'before_cursor_execute', record)
    try:
        assert state(request_api, admin, job)['state'] == 'queued'
    finally:
        event.remove(async_engine.sync_engine, 'before_cursor_execute', record)
    assert all('scoring_jobs.snapshot' not in statement for statement in statements)
