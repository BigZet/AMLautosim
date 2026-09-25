import pytest

from scripts.seed_database import seed
from src.aml_workshop_simulator.schemas.participant_state import ParticipantStateOut


def test_openapi_contract(request_api):
    schema = request_api("GET", "/openapi.json")
    paths = schema["paths"]
    assert "/api/v1/admin/rounds/{round_id}/close" not in paths
    for path in (
        "/rounds/current",
        "/rounds/current/state",
        "/rounds/{round_id}/scenario",
        "/rounds/{round_id}/result",
    ):
        assert "get" in paths["/api/v1" + path]
    operation = paths["/api/v1/rounds/{round_id}/leaderboard"]["get"]
    assert operation["security"] == [{"SessionId": []}]
    assert "reveal" not in {p["name"] for p in operation["parameters"]}
    models = schema["components"]["schemas"]
    assert set(models["ScenarioSubmitIn"]["required"]) == {
        "steps",
        "expected_revision",
        "client_mutation_id",
    }
    assert "masked" not in models["LeaderboardRowOut"]["properties"]
    assert "revealed" not in models["LeaderboardPageOut"]["properties"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"steps": [], "expected_revision": 0},
        {"steps": [], "expected_revision": -1, "client_mutation_id": "not-a-uuid"},
    ],
)
def test_validation_error_envelope(api, player, active_round, payload):
    response = api.post(
        f"/api/v1/rounds/{active_round}/scenario/submit",
        headers=player["headers"],
        json=payload,
    )
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    assert body["details"]


def test_state_response_matches_typed_contract(request_api, player):
    body = request_api("GET", "/rounds/current/state", player["headers"])
    assert ParticipantStateOut.model_validate(body).model_dump(mode="json") == body


def test_migration_and_seed_are_current_and_idempotent(api, sql):
    from src.aml_workshop_simulator.api.routers.health import _expected_heads
    assert {row["version_num"] for row in sql("SELECT version_num FROM alembic_version")} == _expected_heads()
    before = sql("SELECT id, game_config FROM rounds")
    api.portal.call(seed)
    assert sql("SELECT id, game_config FROM rounds") == before
    assert sql("SELECT count(*) AS n FROM users")[0]["n"] == 1
    assert sql("SELECT count(*) AS n FROM action_cards")[0]["n"] == 5
    tables = {
        r["tablename"]
        for r in sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    }
    assert tables == {
        "alembic_version",
        "users",
        "sessions",
        "rounds",
        "scenarios",
        "scoring_results",
        "action_cards",
        "audit_events",
        "auth_rate_limits",
    }


def test_health_and_schema_readiness(api, sql):
    previous = sql("SELECT version_num FROM alembic_version")[0]["version_num"]
    assert api.get("/health/live").json()["status"] == "ok"
    assert api.get("/health/ready").json()["status"] == "ready"
    try:
        sql("UPDATE alembic_version SET version_num='obsolete'")
        response = api.get("/health/ready")
        assert response.status_code == 503 and response.json()["status"] == "not_ready"
        assert api.get("/health/live").json()["status"] == "ok"
    finally:
        sql("UPDATE alembic_version SET version_num=:version", {"version": previous})
