"""RBAC, IDOR, user isolation and privacy of the public projection."""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests.helpers import build_step, put_scenario, valid_chain

ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/action-cards"),
    ("GET", "/api/v1/admin/rounds"),
    ("GET", "/api/v1/admin/rounds/{round_id}"),
    ("GET", "/api/v1/admin/rounds/{round_id}/stats"),
    ("GET", "/api/v1/admin/rounds/{round_id}/participants"),
    ("GET", "/api/v1/admin/rounds/{round_id}/leaderboard"),
    ("GET", "/api/v1/admin/rounds/{round_id}/audit-events"),
    ("POST", "/api/v1/admin/rounds/{round_id}/activate"),
    ("POST", "/api/v1/admin/rounds/{round_id}/start"),
    ("POST", "/api/v1/admin/rounds/{round_id}/stop"),
    ("POST", "/api/v1/admin/rounds/{round_id}/restart"),
    ("GET", "/api/v1/admin/rounds/{round_id}/scoring-plan"),
    ("POST", "/api/v1/admin/rounds/{round_id}/score"),
    ("GET", "/api/v1/admin/rounds/{round_id}/participants/1/scenario-versions/1"),
    ("GET", "/api/v1/admin/round-presets"),
    ("POST", "/api/v1/admin/round-presets"),
    ("GET", "/api/v1/admin/round-presets/1"),
    ("PUT", "/api/v1/admin/round-presets/1"),
    ("DELETE", "/api/v1/admin/round-presets/1"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES, ids=[p for _, p in ADMIN_ROUTES])
def test_participant_is_refused_on_every_admin_route(
    client, participant, active_round, method, path
) -> None:
    url = path.format(round_id=active_round["id"])
    response = client.request(method, url, headers=participant["headers"])
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES, ids=[p for _, p in ADMIN_ROUTES])
def test_anonymous_is_refused_on_every_admin_route(client, active_round, method, path) -> None:
    url = path.format(round_id=active_round["id"])
    response = client.request(method, url)
    assert response.status_code == 401


def test_participants_never_see_each_others_scenarios(
    client, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    first_steps = [build_step(cards["salary"], 50000, 1, "bank")]
    second_steps = [build_step(cards["card_transfer"], 7000, 1, "web")]
    put_scenario(client, round_id, participant["headers"], first_steps)
    put_scenario(client, round_id, second_participant["headers"], second_steps)

    first_view = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    second_view = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=second_participant["headers"]
    ).json()

    assert first_view["participant_id"] == participant["id"]
    assert second_view["participant_id"] == second_participant["id"]
    assert first_view["id"] != second_view["id"]
    assert first_view["steps"][0]["card"]["code"] == "salary"
    assert second_view["steps"][0]["card"]["code"] == "card_transfer"


def test_the_version_history_is_scoped_to_its_own_participant(
    client, participant, second_participant, active_round, cards
) -> None:
    """Two players saving in the same round never see each other's versions."""
    round_id = active_round["id"]
    put_scenario(
        client,
        round_id,
        participant["headers"],
        [build_step(cards["salary"], 50000, 1, "bank")],
    )
    put_scenario(
        client,
        round_id,
        second_participant["headers"],
        [build_step(cards["card_transfer"], 7000, 1, "web")],
    )

    first = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions", headers=participant["headers"]
    ).json()
    second = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions",
        headers=second_participant["headers"],
    ).json()

    assert len(first["rows"]) == 1
    assert len(second["rows"]) == 1
    assert first["rows"][0]["id"] != second["rows"][0]["id"]

    own = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions/1", headers=participant["headers"]
    ).json()
    assert own["steps"][0]["card"]["code"] == "salary"
    other = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions/1",
        headers=second_participant["headers"],
    ).json()
    # The same revision number means a different version for a different player.
    assert other["steps"][0]["card"]["code"] == "card_transfer"


def test_restoring_a_version_cannot_reach_another_participant(
    client, participant, second_participant, active_round, cards
) -> None:
    """A revision that only the other player has is simply not found."""
    round_id = active_round["id"]
    put_scenario(
        client,
        round_id,
        second_participant["headers"],
        [build_step(cards["salary"], 50000, 1, "bank")],
    )
    put_scenario(
        client,
        round_id,
        second_participant["headers"],
        [build_step(cards["salary"], 60000, 1, "bank")],
        expected_revision=1,
    )
    put_scenario(
        client,
        round_id,
        participant["headers"],
        [build_step(cards["card_transfer"], 7000, 1, "web")],
    )

    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/2/restore",
        json={"expected_revision": 1, "client_mutation_id": str(uuid.uuid4())},
        headers=participant["headers"],
    )
    assert response.status_code == 404, response.text


def test_participant_id_cannot_be_injected_through_the_payload(
    client, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    response = client.put(
        f"/api/v1/rounds/{round_id}/scenario",
        json={
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
            "participant_id": second_participant["id"],
            "steps": [],
        },
        headers=participant["headers"],
    )
    assert response.status_code == 422


def test_results_are_not_leaked_between_participants(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    for player in (participant, second_participant):
        saved = put_scenario(client, round_id, player["headers"], valid_chain(cards)).json()
        client.post(
            f"/api/v1/rounds/{round_id}/scenario/submit",
            json={"expected_revision": saved["revision"]},
            headers=player["headers"],
        )
    client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )

    first = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=participant["headers"]
    ).json()
    second = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=second_participant["headers"]
    ).json()
    assert first["scenario_id"] != second["scenario_id"]


def test_public_leaderboard_contains_no_identifiers(
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

    response = client.get(f"/api/v1/rounds/{round_id}/leaderboard")
    body = response.text
    assert participant["email"] not in body
    # The nickname is not in the default projection either: the row carries a
    # neutral placeholder until somebody explicitly asks to reveal names.
    assert participant["display_name"] not in body
    row = response.json()["rows"][0]
    assert set(row) == {
        "rank",
        "display_name",
        "masked",
        "game_score",
        "stealth_score",
        "resource_score",
        "risk_label",
        "is_adjusted",
        "is_current_user",
    }
    assert row["display_name"] == "Игрок #1"
    assert row["masked"] is True


def test_a_revoked_session_cannot_be_replayed(client, participant, active_round) -> None:
    client.delete("/api/v1/auth/session", headers=participant["headers"])
    replay = client.get(
        f"/api/v1/rounds/{active_round['id']}/scenario", headers=participant["headers"]
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "session_revoked"


def test_sql_and_xss_payloads_stay_data(client, participant, active_round, cards, db_dsn) -> None:
    payload = "<script>alert('xss')</script>'; DROP TABLE users; --"
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"x{uuid.uuid4().hex[:8]}@example.com",
            "display_name": payload[:120],
            "password": "correct-horse-42",
        },
    )
    assert registered.status_code == 201
    assert registered.json()["display_name"] == payload[:120]

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM users")
            assert cursor.fetchone()[0] >= 2
    finally:
        connection.close()


def test_error_envelope_never_exposes_internals(client, active_round) -> None:
    response = client.get("/api/v1/rounds/999999/scenario", headers={"X-Session-ID": "nope"})
    body = response.json()
    assert set(body) == {"code", "message", "details", "request_id"}
    assert "Traceback" not in response.text
    assert "postgresql" not in response.text.lower()


def test_request_id_is_echoed(client) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "test-request-id"})
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_admin_detail_is_not_cached(client, admin_headers, participant, active_round) -> None:
    response = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{participant['id']}",
        headers=admin_headers,
    )
    assert response.headers["Cache-Control"] == "no-store"


def test_idor_on_another_round_returns_no_data(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    """A participant may only ever read their own row, whatever id they ask for."""
    round_id = active_round["id"]
    put_scenario(client, round_id, second_participant["headers"], valid_chain(cards))
    own = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    )
    assert own.status_code == 200
    assert own.json() is None
