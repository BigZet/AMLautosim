"""Concurrency against real PostgreSQL connections.

Requests are issued from separate threads released by a shared barrier, so the
races are resolved by PostgreSQL row locks and constraints rather than by test
ordering.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2

from tests.helpers import build_step, put_scenario, valid_chain


def run_in_parallel(*calls):
    """Execute callables simultaneously and return their results in order."""
    barrier = threading.Barrier(len(calls))

    def wrapped(call):
        def inner():
            barrier.wait(timeout=30)
            return call()

        return inner

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(wrapped(call)) for call in calls]
        return [future.result(timeout=60) for future in futures]


def test_two_puts_with_the_same_revision_leave_one_winner(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    first = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()

    steps_a = [build_step(cards["salary"], 20000, 1, "bank")]
    steps_b = [build_step(cards["salary"], 30000, 1, "mobile")]
    responses = run_in_parallel(
        lambda: put_scenario(
            client, round_id, participant["headers"], steps_a,
            expected_revision=first["revision"],
        ),
        lambda: put_scenario(
            client, round_id, participant["headers"], steps_b,
            expected_revision=first["revision"],
        ),
    )
    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 409]
    conflict = next(item for item in responses if item.status_code == 409)
    assert conflict.json()["code"] == "scenario_revision_conflict"

    final = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    assert final["revision"] == first["revision"] + 1


def test_two_first_puts_do_not_create_two_scenarios(
    client, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    steps_a = [build_step(cards["salary"], 20000, 1, "bank")]
    steps_b = [build_step(cards["salary"], 30000, 1, "mobile")]
    responses = run_in_parallel(
        lambda: put_scenario(client, round_id, participant["headers"], steps_a),
        lambda: put_scenario(client, round_id, participant["headers"], steps_b),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM scenarios WHERE round_id = %s AND participant_id = %s",
                (round_id, participant["id"]),
            )
            assert cursor.fetchone()[0] == 1
    finally:
        connection.close()


def test_a_retried_put_never_creates_a_second_revision(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    chain = valid_chain(cards)
    mutation = str(uuid.uuid4())
    responses = run_in_parallel(
        lambda: put_scenario(
            client, round_id, participant["headers"], chain, mutation_id=mutation
        ),
        lambda: put_scenario(
            client, round_id, participant["headers"], chain, mutation_id=mutation
        ),
    )
    successes = [item for item in responses if item.status_code == 200]
    assert successes, [item.json() for item in responses]
    current = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    assert current["revision"] == 1


def test_submit_racing_with_an_edit_keeps_the_scenario_consistent(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    edited = [dict(step) for step in saved["steps"]]
    edited[2]["amount"] = "61000.00"

    responses = run_in_parallel(
        lambda: client.post(
            f"/api/v1/rounds/{round_id}/scenario/submit",
            json={"expected_revision": saved["revision"]},
            headers=participant["headers"],
        ),
        lambda: put_scenario(
            client, round_id, participant["headers"], edited,
            expected_revision=saved["revision"],
        ),
    )
    assert all(response.status_code in (200, 409) for response in responses)
    final = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    assert final["status"] in {"draft", "submitted"}
    if final["status"] == "submitted":
        assert final["submitted_at"] is not None


def test_two_activations_produce_one_active_round(client, admin_headers) -> None:
    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    draft = next(item for item in rounds if item["status"] == "draft")
    second = client.post(
        "/api/v1/admin/rounds",
        json={"title": "Параллельный раунд", "game_config": draft["game_config"]},
        headers=admin_headers,
    ).json()

    responses = run_in_parallel(
        lambda: client.post(
            f"/api/v1/admin/rounds/{draft['id']}/activate",
            headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
        lambda: client.post(
            f"/api/v1/admin/rounds/{second['id']}/activate",
            headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    listing = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    assert len([item for item in listing if item["status"] == "active"]) == 1


def test_two_score_commands_score_the_round_once(
    client, admin_headers, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )

    responses = run_in_parallel(
        lambda: client.post(
            f"/api/v1/admin/rounds/{round_id}/score",
            headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
        lambda: client.post(
            f"/api/v1/admin/rounds/{round_id}/score",
            headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
        ),
    )
    statuses = sorted(response.status_code for response in responses)
    assert 200 in statuses
    assert all(code in (200, 409) for code in statuses)

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM scoring_results")
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT count(*) FROM audit_events WHERE event_type = 'round_scored'"
            )
            assert cursor.fetchone()[0] == 1
    finally:
        connection.close()


def test_block_racing_with_a_participant_request(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))
    responses = run_in_parallel(
        lambda: client.put(
            f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}/access",
            json={
                "blocked": True,
                "reason": "Блокировка во время активного запроса",
                "expected_access_revision": 1,
            },
            headers=admin_headers,
        ),
        lambda: client.get(
            f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
        ),
    )
    assert responses[0].status_code == 200
    assert responses[1].status_code in (200, 401, 403)
    after = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    )
    assert after.status_code in (401, 403)


def test_two_adjustment_writers_conflict(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )

    url = (
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/leaderboard-adjustment"
    )
    responses = run_in_parallel(
        lambda: client.put(
            url,
            json={
                "expected_revision": 0,
                "game_score_override": "70.00",
                "reason": "Первая параллельная корректировка",
            },
            headers=admin_headers,
        ),
        lambda: client.put(
            url,
            json={
                "expected_revision": 0,
                "game_score_override": "80.00",
                "reason": "Вторая параллельная корректировка",
            },
            headers=admin_headers,
        ),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(item for item in responses if item.status_code == 409)
    assert conflict.json()["code"] == "adjustment_revision_conflict"
