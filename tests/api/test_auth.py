import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/rounds/current",
        "/rounds/1/cards",
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
def test_ip_scoped_limit_does_not_lock_account_for_other_ips(request_api, api, player, monkeypatch, sql, attempts):
    from fastapi.testclient import TestClient
    from src.aml_workshop_simulator.core.config import settings

    monkeypatch.setattr(settings, "AUTH_PAIR_PER_MINUTE", attempts)
    sql("TRUNCATE auth_rate_limits")
    for _ in range(attempts):
        request_api("POST", "/auth/login", body={"email": player["email"], "password": "wrong"}, status=401)
    payload = {"email": player["email"], "password": "participant123"}
    response = api.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    assert sql("SELECT locked_until FROM users WHERE id=:id", {"id": player["id"]})[0]["locked_until"] is None
    with TestClient(api.app, client=("192.0.2.12", 1234)) as other:
        assert other.post("/api/v1/auth/login", json=payload).status_code == 200
    sql("TRUNCATE auth_rate_limits")
    assert request_api("POST", "/auth/login", body=payload)["session_id"]


def test_spoofed_client_headers_do_not_bypass_early_limit(api, player, monkeypatch, sql):
    from src.aml_workshop_simulator.core.config import settings
    from src.aml_workshop_simulator.services import authentication

    monkeypatch.setattr(settings, "AUTH_PAIR_PER_MINUTE", 1)
    sql("TRUNCATE auth_rate_limits")
    payload = {"email": player["email"], "password": "wrong"}
    assert api.post("/api/v1/auth/login", json=payload).status_code == 401
    monkeypatch.setattr(authentication, "verify_password", lambda *a: pytest.fail("Hash verification must be after the gate"))
    response = api.post("/api/v1/auth/login", json=payload,
                        headers={"X-Forwarded-For": "203.0.113.12", "X-AML-Client-IP": "203.0.113.12", "X-AML-Client-Signature": "forged"})
    assert response.status_code == 429


def test_known_unknown_invalid_login_has_same_contract(api, player):
    responses = [api.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
                 for email in (player["email"], "unknown@example.com")]
    assert [r.status_code for r in responses] == [401, 401]
    assert responses[0].json()["code"] == responses[1].json()["code"]
    assert responses[0].json()["message"] == responses[1].json()["message"]


def test_trusted_ui_signed_context_keeps_client_ips_separate(api, player, monkeypatch, sql):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from src.aml_workshop_simulator.core.client_context import sign_context
    from src.aml_workshop_simulator.core.config import settings

    monkeypatch.setattr(settings, 'AUTH_CONTEXT_SECRET', SecretStr('test-signing-secret'))
    monkeypatch.setattr(settings, 'AUTH_TRUSTED_UI_CIDRS', ['192.0.2.10/32'])
    monkeypatch.setattr(settings, 'AUTH_PAIR_PER_MINUTE', 1)
    sql('TRUNCATE auth_rate_limits')
    with TestClient(api.app, client=('192.0.2.10', 1234)) as ui:
        payload = {'email': player['email'], 'password': 'wrong'}
        headers = sign_context('203.0.113.7', 'login', player['email'], 'test-signing-secret')
        assert ui.post('/api/v1/auth/login', json=payload, headers=headers).status_code == 401
        assert ui.post('/api/v1/auth/login', json=payload, headers=headers).status_code == 429
        headers = sign_context('203.0.113.8', 'login', player['email'], 'test-signing-secret')
        payload['password'] = 'participant123'
        assert ui.post('/api/v1/auth/login', json=payload, headers=headers).status_code == 200


def test_sixty_registrations_and_logins_share_nat(api):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    import time
    import json

    def enter(index):
        email = f"{uuid4().hex}@example.com"
        registered = api.post("/api/v1/auth/register", json={"email": email, "display_name": f"Участник {index}", "password": "participant123"})
        logged = api.post("/api/v1/auth/login", json={"email": email, "password": "participant123"})
        return registered.status_code, logged.status_code

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(enter, range(60)))
    elapsed = time.monotonic() - started
    assert statuses == [(201, 200)] * 60
    assert elapsed < 60
    print(json.dumps({"nat_participants": 60, "registration_and_login_seconds": elapsed}))


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
