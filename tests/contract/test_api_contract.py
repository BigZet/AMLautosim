"""OpenAPI surface and the Streamlit API client contract."""

from __future__ import annotations

import uuid

import httpx
import pytest

from src.aml_workshop_simulator.ui.shared.api_client import (
    TIMEOUTS,
    APIClientError,
    SimulatorAPIClient,
)

DOCUMENTED_OPERATIONS = {
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/login"),
    ("get", "/api/v1/auth/session"),
    ("delete", "/api/v1/auth/session"),
    ("get", "/api/v1/rounds/active"),
    ("get", "/api/v1/rounds/mine"),
    ("get", "/api/v1/rounds/{round_id}/cards"),
    ("get", "/api/v1/rounds/{round_id}/scenario"),
    ("put", "/api/v1/rounds/{round_id}/scenario"),
    ("post", "/api/v1/rounds/{round_id}/scenario/submit"),
    ("get", "/api/v1/rounds/{round_id}/result"),
    ("get", "/api/v1/rounds/{round_id}/leaderboard"),
    ("get", "/api/v1/admin/action-cards"),
    ("post", "/api/v1/admin/rounds"),
    ("get", "/api/v1/admin/rounds"),
    ("get", "/api/v1/admin/rounds/{round_id}"),
    ("put", "/api/v1/admin/rounds/{round_id}"),
    ("post", "/api/v1/admin/rounds/{round_id}/activate"),
    ("post", "/api/v1/admin/rounds/{round_id}/score"),
    ("get", "/api/v1/admin/rounds/{round_id}/stats"),
    ("get", "/api/v1/admin/rounds/{round_id}/leaderboard"),
    ("get", "/api/v1/admin/rounds/{round_id}/participants"),
    ("get", "/api/v1/admin/rounds/{round_id}/participants/{participant_id}"),
    ("put", "/api/v1/admin/rounds/{round_id}/participants/{participant_id}/access"),
    (
        "put",
        "/api/v1/admin/rounds/{round_id}/participants/{participant_id}"
        "/leaderboard-adjustment",
    ),
    (
        "delete",
        "/api/v1/admin/rounds/{round_id}/participants/{participant_id}"
        "/leaderboard-adjustment",
    ),
    ("get", "/api/v1/admin/rounds/{round_id}/audit-events"),
    ("get", "/health/live"),
    ("get", "/health/ready"),
}


def openapi(client) -> dict:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_every_documented_endpoint_exists(client) -> None:
    spec = openapi(client)
    published = {
        (method, path)
        for path, operations in spec["paths"].items()
        for method in operations
    }
    assert DOCUMENTED_OPERATIONS <= published, DOCUMENTED_OPERATIONS - published


def test_no_unversioned_application_endpoints_remain(client) -> None:
    spec = openapi(client)
    for path in spec["paths"]:
        assert path.startswith("/api/v1") or path.startswith("/health/"), path


def test_operation_ids_are_stable_and_unique(client) -> None:
    spec = openapi(client)
    ids = [
        operation["operationId"]
        for operations in spec["paths"].values()
        for operation in operations.values()
    ]
    assert len(ids) == len(set(ids))
    assert "rounds_scenario_put" in ids
    assert "admin_round_score" in ids


def test_health_live_does_not_touch_the_database(client) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api", "version": "1.0.0"}


def test_health_ready_reports_migrations_and_rulesets(client) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["migrations"] == "head"
    assert "game-rules-v2" in body["checks"]["ruleset_versions"]


def test_documented_error_envelope_shape(client, active_round) -> None:
    response = client.get("/api/v1/rounds/999999/cards")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "round_not_found"
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["request_id"]


def test_native_pydantic_failures_use_the_same_envelope(client, participant, active_round) -> None:
    response = client.put(
        f"/api/v1/rounds/{active_round['id']}/scenario",
        json={"expected_revision": "not-a-number"},
        headers=participant["headers"],
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["details"]["violations"]


def test_short_registration_password_has_an_actionable_message(client) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "short-password@example.com",
            "display_name": "Игрок",
            "password": "short1234",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["message"] == "Пароль должен содержать не менее 10 символов."
    assert body["details"]["violations"] == [
        {
            "field": "password",
            "reason": "string_too_short",
            "message": "Пароль должен содержать не менее 10 символов.",
        }
    ]


def test_money_is_serialised_as_a_fixed_point_string(client, active_round, cards) -> None:
    card = cards["salary"]
    assert card["min_amount"] == "10000.00"
    assert card["max_amount"] == "150000.00"
    assert card["fee_rate"] == "0.000000"


def test_card_contract_exposes_channels_and_labels(cards) -> None:
    for card in cards.values():
        assert card["channels"]
        assert set(card["channel_labels"]) == set(card["channels"])
        assert card["round_frequency_limit"] >= 1


# --------------------------------------------------------------------------
# Streamlit API client
# --------------------------------------------------------------------------


def test_api_client_uses_the_versioned_prefix() -> None:
    api = SimulatorAPIClient(base_url="http://api.internal")
    assert api._url("/rounds/active") == "/api/v1/rounds/active"
    assert api.base_url == "http://api.internal"


def test_api_client_never_stores_a_session_id_on_the_transport() -> None:
    api = SimulatorAPIClient(base_url="http://api.internal")
    assert "X-Session-ID" not in api._client.headers
    headers = api._headers("secret-session")
    assert headers["X-Session-ID"] == "secret-session"
    assert "X-Session-ID" not in api._client.headers


def test_api_client_sends_a_request_id_per_call() -> None:
    api = SimulatorAPIClient(base_url="http://api.internal")
    first = api._headers(None)["X-Request-ID"]
    second = api._headers(None)["X-Request-ID"]
    assert first != second
    assert api._headers(None, request_id="fixed")["X-Request-ID"] == "fixed"


def test_api_client_timeout_profile_matches_the_documentation() -> None:
    assert TIMEOUTS["GET"].read == 10.0
    assert TIMEOUTS["WRITE"].read == 15.0
    assert TIMEOUTS["SCORE"].read == 30.0


def test_api_client_maps_the_error_envelope() -> None:
    api = SimulatorAPIClient(base_url="http://api.internal")
    response = httpx.Response(
        409,
        json={
            "code": "scenario_revision_conflict",
            "message": "Сценарий изменен в другом окне",
            "details": {"current_revision": 4},
            "request_id": "abc",
        },
        request=httpx.Request("PUT", "http://api.internal/api/v1/rounds/1/scenario"),
    )
    with pytest.raises(APIClientError) as raised:
        api._handle_response(response)
    error = raised.value
    assert error.code == "scenario_revision_conflict"
    assert error.status_code == 409
    assert error.details == {"current_revision": 4}


def test_api_client_handles_a_non_json_server_error() -> None:
    api = SimulatorAPIClient(base_url="http://api.internal")
    response = httpx.Response(
        502,
        text="<html>bad gateway</html>",
        request=httpx.Request("GET", "http://api.internal/api/v1/rounds/active"),
    )
    with pytest.raises(APIClientError) as raised:
        api._handle_response(response)
    assert raised.value.status_code == 502


def test_api_client_put_sends_the_mutation_id(client, participant, active_round, cards) -> None:
    """The client is exercised against the real app through a mounted transport."""
    api = SimulatorAPIClient(base_url="http://testserver")
    api._client = client
    api.api_prefix = "/api/v1"
    mutation = str(uuid.uuid4())
    from tests.helpers import valid_chain

    chain = valid_chain(cards)
    result = api.put_scenario(
        active_round["id"], chain, 0, participant["session_id"], client_mutation_id=mutation
    )
    assert result["revision"] == 1
    # A retry of the very same command must not create a second revision.
    replay = api.put_scenario(
        active_round["id"], chain, 0, participant["session_id"], client_mutation_id=mutation
    )
    assert replay["revision"] == 1
