import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/rounds/current/state",
        "/rounds/1/scenario",
        "/rounds/1/result",
        "/rounds/1/leaderboard",
        "/admin/rounds/current",
    ],
)
def test_session_required(request_api, path):
    request_api("GET", path, status=401)
    request_api("GET", path, {"X-Session-ID": "invalid"}, status=401)


def test_audience_and_role_isolation(request_api, admin, player, round_id):
    request_api("GET", "/admin/rounds/current", player["headers"], status=403)
    request_api("GET", f"/rounds/{round_id}/leaderboard", admin, status=403)
    request_api(
        "POST",
        "/auth/login",
        body={
            "email": player["email"],
            "password": "participant123",
            "audience": "admin",
        },
        status=403,
    )


def test_logout_revokes_session(request_api, player):
    h = player["headers"]
    assert request_api("GET", "/auth/session", h)["id"] == player["id"]
    request_api("DELETE", "/auth/session", h, status=204)
    request_api("GET", "/auth/session", h, status=401)
    request_api("DELETE", "/auth/session", h, status=204)


def test_long_password_and_normalized_identity(request_api, player_factory):
    player = player_factory("  Имя участника  ", password="я" * 100)
    assert player["display_name"] == "Имя участника"
    request_api(
        "POST",
        "/auth/register",
        body={
            "email": player["email"].upper(),
            "password": "participant123",
            "display_name": "Повтор",
        },
        status=409,
    )
    request_api(
        "POST",
        "/auth/login",
        body={"email": player["email"], "password": "wrong"},
        status=401,
    )


def test_expired_session(request_api, player, sql):
    sql(
        "UPDATE sessions SET expires_at = now() - interval '1 second' WHERE user_id=:id",
        {"id": player["id"]},
    )
    request_api("GET", "/auth/session", player["headers"], status=401)


def test_participant_data_is_private(
    request_api, player, player_factory, active_round, chain, command
):
    request_api(
        "POST",
        f"/rounds/{active_round}/scenario/submit",
        player["headers"],
        command(chain()),
    )
    other = player_factory()
    state = request_api("GET", "/rounds/current/state", other["headers"])
    assert state["scenario"] is None and state["result"] is None and state["can_edit"]
    request_api(
        "GET",
        f"/admin/rounds/{active_round}/participants/{player['id']}",
        other["headers"],
        status=403,
    )


@pytest.mark.parametrize("attempts", [1, 2])
def test_login_lockout_and_recovery(
    request_api, api, player, monkeypatch, sql, attempts
):
    from src.aml_workshop_simulator.core.config import Settings, settings

    validated = Settings(
        _env_file=None, LOGIN_MAX_FAILED_ATTEMPTS=attempts, LOGIN_LOCKOUT_MINUTES=1
    )
    monkeypatch.setattr(
        settings, "LOGIN_MAX_FAILED_ATTEMPTS", validated.LOGIN_MAX_FAILED_ATTEMPTS
    )
    monkeypatch.setattr(
        settings, "LOGIN_LOCKOUT_MINUTES", validated.LOGIN_LOCKOUT_MINUTES
    )
    for _ in range(attempts):
        request_api(
            "POST",
            "/auth/login",
            body={"email": player["email"], "password": "wrong"},
            status=401,
        )
    payload = {"email": player["email"], "password": "participant123"}
    response = api.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    sql(
        "UPDATE users SET locked_until=now() - interval '1 second' WHERE id=:id",
        {"id": player["id"]},
    )
    assert request_api("POST", "/auth/login", body=payload)["session_id"]


def test_minimum_session_lifetime_allows_login_and_expires(
    request_api, player, monkeypatch, sql
):
    from src.aml_workshop_simulator.core.config import Settings, settings

    validated = Settings(_env_file=None, SESSION_TTL_MINUTES=1)
    monkeypatch.setattr(settings, "SESSION_TTL_MINUTES", validated.SESSION_TTL_MINUTES)
    session = request_api(
        "POST",
        "/auth/login",
        body={"email": player["email"], "password": "participant123"},
    )
    headers = {"X-Session-ID": session["session_id"]}
    assert request_api("GET", "/auth/session", headers)["id"] == player["id"]
    durations = sql(
        "SELECT EXTRACT(EPOCH FROM (expires_at-created_at)) AS seconds "
        "FROM sessions WHERE user_id=:id ORDER BY created_at DESC LIMIT 1",
        {"id": player["id"]},
    )
    assert durations[0]["seconds"] == 60
    sql(
        "UPDATE sessions SET expires_at=now() - interval '1 second' WHERE user_id=:id",
        {"id": player["id"]},
    )
    request_api("GET", "/auth/session", headers, status=401)
