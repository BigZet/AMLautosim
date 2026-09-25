"""Real PostgreSQL round-trips and HTTP availability/atomicity boundaries."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import select

from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.session import AsyncSessionLocal
from src.aml_workshop_simulator.schemas.round_config import parse_game_config
from src.aml_workshop_simulator.services.configuration import freeze_game_config
from src.aml_workshop_simulator.services.round_configuration import config_version

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/contracts"


@pytest.mark.parametrize("version", ["7", "8", "9", "11", "abc"])
@pytest.mark.parametrize("endpoint", ["game-config/default", "action-cards", "rounds/1/restart"])
def test_invalid_query_version_rejected_before_work(version, endpoint, api, admin, monkeypatch):
    from src.aml_workshop_simulator.api.routers.admin import rounds

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid version reached config or service")

    monkeypatch.setattr(rounds, "game_config", forbidden)
    monkeypatch.setattr(rounds, "catalog_cards", forbidden)
    monkeypatch.setattr(rounds.operations, "restart", forbidden)
    response = api.request("POST" if endpoint.endswith("restart") else "GET",
                           f"/api/v1/admin/{endpoint}?schema_version={version}", headers=admin)
    assert response.status_code == 422


@pytest.mark.parametrize("version", [7, 8, 9, 11, "abc", True, 8.0])
def test_direct_restart_rejects_version_before_database(version):
    import asyncio
    from src.aml_workshop_simulator.services.admin_rounds import restart
    from src.aml_workshop_simulator.core.errors import ValidationFailed

    class NoDatabase:
        async def execute(self, *args):
            raise AssertionError("Invalid version acquired a database lock")

    with pytest.raises(ValidationFailed):
        asyncio.run(restart(NoDatabase(), 1, 1, None, version))


@pytest.mark.parametrize("version", [None, 10])
def test_supported_query_versions_and_default(version, request_api, admin):
    query = "" if version is None else f"?schema_version={version}"
    config = request_api("GET", "/admin/game-config/default" + query, admin)
    assert config["schema_version"] == (version or 10)
    assert request_api("GET", "/admin/action-cards" + query, admin)


def expanded(config):
    result = deepcopy(config)
    result.pop("card_snapshots", None)
    result.pop("config_version", None)
    result.pop("risk_model", None)
    result["schema_version"] = 8
    result["behavior"] = json.loads(
        (FIXTURES / "expanded-v8-behavior.json").read_text()
    )
    return result


def state(sql):
    return {
        table: sql(f"SELECT * FROM {table} ORDER BY id")
        for table in ("rounds", "scenarios", "scoring_results", "audit_events")
    }


@pytest.mark.parametrize("version", [7, 8])
def test_snapshot_roundtrip_in_postgresql(
    version, api, request_api, admin, player, round_id, sql
):
    from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
    config = expanded_game_config()
    if version == 7:
        from src.aml_workshop_simulator.core.game_config import base_game_config

        config = base_game_config()

    async def freeze():
        async with AsyncSessionLocal() as db:
            cards = list((await db.execute(select(ActionCard))).scalars())
            return freeze_game_config(config, cards)

    frozen = api.portal.call(freeze)
    assert frozen["schema_version"] == version
    frozen["config_version"] = config_version(frozen)
    # Only the fixture writes v8 directly; ordinary create/update APIs deny it.
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(frozen), "id": round_id},
    )
    stored = sql("SELECT game_config FROM rounds WHERE id=:id", {"id": round_id})[0][
        "game_config"
    ]
    assert stored == frozen
    parsed = parse_game_config(stored, stored=True)
    assert parsed.schema_version == version
    output = request_api("GET", f"/admin/rounds/{round_id}", admin)["game_config"]
    public = request_api("GET", "/rounds/current/state", player["headers"])["round"][
        "game_config"
    ]
    assert output == public == parsed.model_dump(mode="json")
    if version == 8:
        assert output["behavior"] == parse_game_config(config).dump()["behavior"]
        assert output["config_version"].startswith("round-config-v8:")
    else:
        assert "behavior" not in output
    assert (
        sql("SELECT game_config FROM rounds WHERE id=:id", {"id": round_id})[0][
            "game_config"
        ]
        == frozen
    )


def test_expanded_create_is_blocked_before_writes(request_api, admin, sql):
    config = request_api("GET", "/admin/game-config/default", admin)
    config["behavior"].pop("release")
    sql("TRUNCATE rounds, audit_events CASCADE")
    before = state(sql)
    error = request_api(
        "POST",
        "/admin/rounds",
        admin,
        {"title": "Не готово", "game_config": config},
        409,
    )
    assert error["code"] == "round_contract_not_ready"
    assert state(sql) == before


@pytest.mark.parametrize(
    "kind,status",
    [("expanded", 409), ("incomplete", 422), ("unknown", 422), ("bypass", 422)],
)
def test_config_rejection_is_atomic(kind, status, request_api, admin, round_id, sql):
    config = request_api("GET", "/admin/game-config/default", admin)
    if kind == "expanded":
        config["behavior"].pop("release")
    elif kind == "incomplete":
        del config["behavior"]["profile"]
    elif kind == "unknown":
        config["schema_version"] = 99
    elif kind == "bypass":
        config["allow_experimental"] = True
    before = state(sql)
    error = request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {
            "expected_config_revision": 1,
            "title": "Не должно сохраниться",
            "game_config": config,
        },
        status,
    )
    if kind == "expanded":
        assert error["code"] == "round_contract_immutable"
    assert state(sql) == before


@pytest.mark.parametrize("status", ["draft", "active"])
def test_stored_expanded_start_is_blocked(status, request_api, admin, round_id, sql):
    config = request_api("GET", f"/admin/rounds/{round_id}", admin)["game_config"]
    config["behavior"].pop("release")
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb), status=:status WHERE id=:id",
        {"config": json.dumps(config), "status": status, "id": round_id},
    )
    before = state(sql)
    error = request_api("POST", f"/admin/rounds/{round_id}/start", admin, status=409)
    assert error["code"] == "round_contract_not_ready"
    assert state(sql) == before


def test_no_evaluation_or_cutoff_for_injected_expanded_round(
    request_api, admin, player, active_round, chain, command, sql
):
    steps = chain()
    path = f"/rounds/{active_round}/scenario"
    request_api("PUT", path, player["headers"], command(steps))
    config = request_api("GET", f"/admin/rounds/{active_round}", admin)["game_config"]
    config["behavior"].pop("release")
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    page = request_api("GET", "/rounds/current/state", player["headers"])
    assert not page["can_edit"] and not page["can_submit"]
    assert not page["round"]["accepts_changes"]
    before = state(sql)
    for method, url, headers, payload in [
        ("POST", path + "/preview", player["headers"], {"steps": steps}),
        ("PUT", path, player["headers"], command(steps, 1)),
        ("POST", path + "/submit", player["headers"], command(steps, 1)),
        ("POST", f"/admin/rounds/{active_round}/score?wait=true", admin, None),
    ]:
        error = request_api(method, url, headers, payload, 409)
        assert error["code"] == "round_contract_not_ready"
        assert state(sql) == before


def test_legacy_golden_snapshot_cannot_start_online(
    request_api, admin, player, round_id, command, sql
):
    golden = json.loads((FIXTURES / "legacy-v7.json").read_text())
    config = golden["config"]
    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": round_id},
    )
    before = state(sql)
    error = request_api("POST", f"/admin/rounds/{round_id}/start", admin, status=409)
    assert error["code"] == "model_contract_mismatch"
    assert state(sql) == before
    # Historical numeric golden expectations are retained in the pure-engine unit tests.


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
