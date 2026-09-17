"""Audit reproductions. Run with: pytest -p tests.conftest <this file>."""

from datetime import UTC, datetime

from src.aml_workshop_simulator.core.config import settings


def test_zero_session_ttl_issues_already_expired_session(api, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_TTL_MINUTES", 0)
    response = api.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "admin12345", "audience": "admin"
    })
    assert response.status_code == 200, response.text
    session = response.json()
    assert datetime.fromisoformat(session["expires_at"]) <= datetime.now(UTC)
    check = api.get("/api/v1/auth/session", headers={"X-Session-ID": session["session_id"]})
    assert check.status_code == 401
    assert check.json()["code"] == "session_expired"
    print("CONFIRMED: SESSION_TTL_MINUTES=0 -> login 200 -> session 401 session_expired")


def test_negative_lockout_never_enforces_temporary_lock(api, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 1)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_MINUTES", -1)
    responses = [api.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "wrong-password", "audience": "admin"
    }) for _ in range(3)]
    assert [r.status_code for r in responses] == [401, 401, 401]
    assert all(r.json()["code"] == "invalid_credentials" for r in responses)
    print("CONFIRMED: LOGIN_LOCKOUT_MINUTES=-1 and max attempts 1 -> three 401 responses, no 429")
