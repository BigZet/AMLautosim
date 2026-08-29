"""Server-side session lifecycle against PostgreSQL 16."""

from __future__ import annotations

import uuid

import psycopg2

from src.aml_workshop_simulator.core.security import hash_session_id
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, PARTICIPANT_PASSWORD, register_participant


def test_register_login_session_and_logout(client) -> None:
    email = f"p{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Игрок", "password": PARTICIPANT_PASSWORD},
    )
    assert created.status_code == 201
    assert "password" not in created.text
    assert created.json()["role"] == "participant"

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PARTICIPANT_PASSWORD, "audience": "play"},
    )
    assert logged_in.status_code == 200
    session_id = logged_in.json()["session_id"]

    profile = client.get("/api/v1/auth/session", headers={"X-Session-ID": session_id})
    assert profile.status_code == 200
    assert profile.json()["role"] == "participant"
    assert profile.json()["audience"] == "play"

    logout = client.delete("/api/v1/auth/session", headers={"X-Session-ID": session_id})
    assert logout.status_code == 204

    after = client.get("/api/v1/auth/session", headers={"X-Session-ID": session_id})
    assert after.status_code == 401
    assert after.json()["code"] == "session_revoked"


def test_only_the_hash_of_the_session_id_is_stored(client, db_dsn) -> None:
    participant = register_participant(client)
    raw = participant["session_id"]
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT session_id_hash FROM sessions")
            stored = {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()
    assert raw not in stored
    assert hash_session_id(raw) in stored


def test_duplicate_email_is_rejected(client) -> None:
    email = f"p{uuid.uuid4().hex[:8]}@example.com"
    payload = {"email": email, "display_name": "Игрок", "password": PARTICIPANT_PASSWORD}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "email_already_registered"


def test_email_is_normalised_before_the_unique_check(client) -> None:
    email = f"P{uuid.uuid4().hex[:8]}@Example.COM"
    payload = {"email": email, "display_name": "Игрок", "password": PARTICIPANT_PASSWORD}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post(
        "/api/v1/auth/register", json={**payload, "email": email.lower()}
    )
    assert duplicate.status_code == 409


def test_wrong_password_and_unknown_email_are_indistinguishable(client) -> None:
    participant = register_participant(client)
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": participant["email"], "password": "wrong-password", "audience": "play"},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password", "audience": "play"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]
    assert wrong.json()["code"] == unknown.json()["code"]


def test_repeated_failures_lock_the_account_temporarily(client) -> None:
    participant = register_participant(client)
    codes = []
    for _ in range(12):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": participant["email"], "password": "nope", "audience": "play"},
        )
        codes.append(response.json()["code"])
    assert "login_temporarily_locked" in codes


def test_audience_separation(client, admin_headers) -> None:
    participant = register_participant(client)
    as_admin = client.post(
        "/api/v1/auth/login",
        json={
            "email": participant["email"],
            "password": PARTICIPANT_PASSWORD,
            "audience": "admin",
        },
    )
    assert as_admin.status_code == 403

    admin_as_player = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "audience": "play"},
    )
    assert admin_as_player.status_code == 403


def test_play_session_cannot_reach_admin_routes(client, participant, active_round) -> None:
    response = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/stats", headers=participant["headers"]
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_missing_and_invalid_sessions_have_distinct_codes(client, active_round) -> None:
    missing = client.get(f"/api/v1/rounds/{active_round['id']}/scenario")
    assert missing.status_code == 401
    assert missing.json()["code"] == "session_missing"

    invalid = client.get(
        f"/api/v1/rounds/{active_round['id']}/scenario",
        headers={"X-Session-ID": "not-a-real-session"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "session_invalid"


def test_two_browsers_of_one_user_are_independent(client) -> None:
    participant = register_participant(client)
    second = client.post(
        "/api/v1/auth/login",
        json={
            "email": participant["email"],
            "password": PARTICIPANT_PASSWORD,
            "audience": "play",
        },
    )
    second_headers = {"X-Session-ID": second.json()["session_id"]}
    assert second.json()["session_id"] != participant["session_id"]

    client.delete("/api/v1/auth/session", headers=participant["headers"])
    assert client.get("/api/v1/auth/session", headers=participant["headers"]).status_code == 401
    assert client.get("/api/v1/auth/session", headers=second_headers).status_code == 200


def test_login_rotates_the_session_id(client) -> None:
    participant = register_participant(client)
    again = client.post(
        "/api/v1/auth/login",
        json={
            "email": participant["email"],
            "password": PARTICIPANT_PASSWORD,
            "audience": "play",
        },
    )
    assert again.json()["session_id"] != participant["session_id"]
