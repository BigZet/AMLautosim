"""Scoring must publish everything or nothing."""

from __future__ import annotations

import uuid

import psycopg2

from aml_workshop_simulator.services import scoring_service
from tests.helpers import put_scenario, valid_chain


def submit(client, round_id, headers, cards) -> None:
    saved = put_scenario(client, round_id, headers, valid_chain(cards)).json()
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_a_failure_in_the_middle_of_the_batch_publishes_nothing(
    client, admin_headers, participant, second_participant, active_round, cards, db_dsn, monkeypatch
) -> None:
    round_id = active_round["id"]
    submit(client, round_id, participant["headers"], cards)
    submit(client, round_id, second_participant["headers"], cards)

    def explode(index: int, scenario) -> None:
        if index == 2:
            raise RuntimeError("controlled scoring failure")

    monkeypatch.setattr(scoring_service, "SCORING_FAILURE_HOOK", explode)
    response = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "controlled scoring failure" not in response.text

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM rounds WHERE id = %s", (round_id,))
            assert cursor.fetchone()[0] == "active"
            cursor.execute("SELECT count(*) FROM scoring_results")
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT count(*) FROM scenarios WHERE round_id = %s AND status <> 'submitted'",
                (round_id,),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT count(*) FROM audit_events WHERE event_type = 'round_scored'"
            )
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()

    # Once the fault is removed the batch succeeds exactly once.
    monkeypatch.setattr(scoring_service, "SCORING_FAILURE_HOOK", None)
    retry = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert retry.status_code == 200
    assert retry.json()["scored_count"] == 2

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM scoring_results")
            assert cursor.fetchone()[0] == 2
            cursor.execute("SELECT count(DISTINCT scenario_id) FROM scoring_results")
            assert cursor.fetchone()[0] == 2
    finally:
        connection.close()


def test_repeat_after_completion_does_not_touch_results(
    client, admin_headers, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    submit(client, round_id, participant["headers"], cards)
    client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, game_score, created_at FROM scoring_results")
            before = cursor.fetchall()
    finally:
        connection.close()

    client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, game_score, created_at FROM scoring_results")
            after = cursor.fetchall()
    finally:
        connection.close()
    assert before == after
