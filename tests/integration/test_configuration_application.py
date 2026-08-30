"""The administrator's settings survive persistence and drive participant APIs."""

import asyncio
import uuid
from copy import deepcopy

import psycopg2

from aml_workshop_simulator.core.game_config import base_game_config
from scripts import seed_database


def create_round(client, headers, config):
    response = client.post(
        "/api/v1/admin/rounds",
        headers=headers,
        json={"title": "Проверка конфигурации", "game_config": config},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_default_endpoint_reads_files_and_is_admin_only(
    client, admin_headers, participant
):
    url = "/api/v1/admin/game-config/default"
    assert client.get(url, headers=participant["headers"]).status_code == 403
    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["resources"] == base_game_config()["resources"]
    assert response.json()["resource_rules"] == base_game_config()["resource_rules"]


def test_overrides_reach_cards_preview_submission_and_scoring(
    client, admin_headers, participant
):
    config = base_game_config()
    config["objectives"]["target_outflow"] = "10000.00"
    config["resources"].update(initial_energy=100, initial_time=100)
    config["resource_rules"]["channel_time"]["mobile"] = 6
    config["scoring"]["rules"]["channel_points"]["mobile"] = "21"
    op = next(o for o in config["operations"] if o["code"] == "card_transfer")
    op.update(
        fee_rate="0.023456",
        energy_cost=4,
        time_cost=3,
        risk_weight="40",
        max_frequency=2,
        round_frequency_limit=2,
    )
    op["defaults"] = {"context.has_documents": False}
    round_obj = create_round(client, admin_headers, config)
    rid = round_obj["id"]
    activated = client.post(
        f"/api/v1/admin/rounds/{rid}/activate", headers=admin_headers
    )
    assert activated.status_code == 200, activated.text
    cards = client.get(f"/api/v1/rounds/{rid}/cards").json()
    card = next(c for c in cards if c["code"] == "card_transfer")
    assert card["fee_rate"] == "0.023456"
    assert card["max_frequency"] == 2
    step = {
        "step_id": str(uuid.uuid4()),
        "card": {key: card[key] for key in ("id", "code", "version")},
        "amount": "10000.00",
        "frequency": 1,
        "context": {"channel": "mobile"},
    }
    response = client.post(
        f"/api/v1/rounds/{rid}/scenario/preview",
        headers=participant["headers"],
        json={"steps": [step]},
    )
    assert response.status_code == 200, response.text
    impact = response.json()["resources"]["per_step"][0]
    assert impact["fee"] == "234.56"
    assert impact["energy_cost"] == 4
    assert impact["time_cost"] == 9
    response = client.put(
        f"/api/v1/rounds/{rid}/scenario",
        headers=participant["headers"],
        json={
            "steps": [step],
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["steps"][0]["context"]["has_documents"] is False
    submitted = client.post(
        f"/api/v1/rounds/{rid}/scenario/submit",
        headers=participant["headers"],
        json={"expected_revision": response.json()["revision"]},
    )
    assert submitted.status_code == 200, submitted.text
    scored = client.post(
        f"/api/v1/admin/rounds/{rid}/score",
        headers=admin_headers,
        json={"confirm": True},
    )
    assert scored.status_code == 200, scored.text
    result = client.get(f"/api/v1/rounds/{rid}/result", headers=participant["headers"])
    assert result.status_code == 200, result.text
    factors = result.json()["explanation"]["all_factors"]
    assert (
        next(f for f in factors if f["code"] == "card:card_transfer")["points"]
        == "40.00"
    )
    assert (
        next(f for f in factors if f["code"] == "channel:mobile")["points"] == "21.00"
    )


def test_reseed_preserves_draft_and_frozen_catalog(client, admin_headers, monkeypatch):
    config = base_game_config()
    config["resources"]["initial_balance"] = "345678.00"
    draft = client.get("/api/v1/admin/rounds", headers=admin_headers).json()[0]
    response = client.put(
        f"/api/v1/admin/rounds/{draft['id']}",
        headers=admin_headers,
        json={
            "expected_config_revision": draft["config_revision"],
            "game_config": config,
        },
    )
    assert response.status_code == 200, response.text
    before = response.json()
    cards_before = client.get(f"/api/v1/rounds/{draft['id']}/cards").json()
    changed = deepcopy(seed_database.CARD_CATALOG)
    next(c for c in changed if c["code"] == "card_transfer")["energy_cost"] = 11
    monkeypatch.setattr(seed_database, "CARD_CATALOG", changed)
    asyncio.run(seed_database.seed())
    after = client.get(
        f"/api/v1/admin/rounds/{draft['id']}", headers=admin_headers
    ).json()
    assert after["game_config"] == before["game_config"]
    assert after["config_revision"] == before["config_revision"]
    assert client.get(f"/api/v1/rounds/{draft['id']}/cards").json() == cards_before
    fresh = create_round(client, admin_headers, config)
    fresh_cards = client.get(f"/api/v1/rounds/{fresh['id']}/cards").json()
    assert (
        next(c for c in fresh_cards if c["code"] == "card_transfer")["costs"]["energy"]
        == 11
    )


def test_client_cannot_replace_server_card_snapshot(client, admin_headers):
    config = base_game_config()
    config["card_snapshots"] = [{"code": "forged", "energy_cost": -100}]
    created = create_round(client, admin_headers, config)
    assert all(
        c["energy_cost"] >= 0 and c["code"] != "forged"
        for c in created["game_config"]["card_snapshots"]
    )


def test_invalid_partial_override_is_rejected(client, admin_headers):
    config = base_game_config()
    config["operations"][0]["min_amount"] = "999999.00"
    response = client.post(
        "/api/v1/admin/rounds",
        headers=admin_headers,
        json={"title": "Неверные лимиты", "game_config": config},
    )
    assert response.status_code == 409, response.text


def test_legacy_round_is_frozen_before_catalog_refresh(
    client, admin_headers, db_dsn, monkeypatch
):
    draft = client.get("/api/v1/admin/rounds", headers=admin_headers).json()[0]
    with psycopg2.connect(db_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE rounds SET game_config = game_config - 'card_snapshots' - 'resource_rules' WHERE id = %s",
                (draft["id"],),
            )
    before = client.get(f"/api/v1/rounds/{draft['id']}/cards").json()
    changed = deepcopy(seed_database.CARD_CATALOG)
    changed[0]["time_cost"] = 12
    monkeypatch.setattr(seed_database, "CARD_CATALOG", changed)
    asyncio.run(seed_database.seed())
    assert client.get(f"/api/v1/rounds/{draft['id']}/cards").json() == before


def test_a_round_naming_a_deleted_card_no_longer_stops_the_seed(
    client, admin_headers, db_dsn, monkeypatch
):
    """The upgrade path of an installation that lost a card version.

    Reducing the catalog deleted the card rows before rounds carried their own
    `card_snapshots`. From then on every API start re-ran the seed, the freeze
    refused a round it could not resolve, the seed exited non-zero and — because
    the container runs the seed before uvicorn — the service never came back.

    The seed now drops the dead reference, exactly as `RoundPolicy` already does
    at play time, and keeps everything else about the round.
    """
    draft = client.get("/api/v1/admin/rounds", headers=admin_headers).json()[0]
    round_id = draft["id"]
    doomed = draft["game_config"]["operations"][-1]["code"]
    survivors = {
        op["code"] for op in draft["game_config"]["operations"] if op["code"] != doomed
    }

    with psycopg2.connect(db_dsn) as connection, connection.cursor() as cursor:
        # The round predates frozen snapshots...
        cursor.execute(
            "UPDATE rounds SET game_config = game_config - 'card_snapshots' "
            "WHERE id = %s",
            (round_id,),
        )
        # ...and an earlier seed already removed the card it names.
        cursor.execute("DELETE FROM action_cards WHERE code = %s", (doomed,))

    reduced = [entry for entry in deepcopy(seed_database.CARD_CATALOG)
               if entry["code"] != doomed]
    monkeypatch.setattr(seed_database, "CARD_CATALOG", reduced)
    asyncio.run(seed_database.seed())

    after = client.get(
        f"/api/v1/admin/rounds/{round_id}", headers=admin_headers
    ).json()
    config = after["game_config"]
    assert {op["code"] for op in config["operations"]} == survivors
    assert len(config["card_snapshots"]) == len(survivors)
    # Everything that is not the dead reference survives untouched.
    assert after["title"] == draft["title"]
    assert after["status"] == draft["status"]
    assert config["resources"] == draft["game_config"]["resources"]
    assert config["objectives"] == draft["game_config"]["objectives"]
    # The round is playable: the surviving cards are the ones it now offers.
    cards = client.get(f"/api/v1/rounds/{round_id}/cards").json()
    assert {card["code"] for card in cards} == survivors
