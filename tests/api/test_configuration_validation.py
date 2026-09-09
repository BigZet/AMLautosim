"""HTTP and seed snapshot creation share semantic validation and preserve state."""

import pytest
from sqlalchemy import select

from scripts import seed_database
from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.session import AsyncSessionLocal
from src.aml_workshop_simulator.services.configuration import freeze_game_config


def test_invalid_update_keeps_round_and_audit_unchanged(
    invalid_game_config, request_api, admin, round_id, sql
):
    config, message = invalid_game_config
    path = f"/admin/rounds/{round_id}"
    before = request_api("GET", path, admin)
    audit = sql("SELECT * FROM audit_events ORDER BY id")
    error = request_api(
        "PUT",
        path,
        admin,
        {"expected_config_revision": before["config_revision"], "game_config": config},
        status=409,
    )
    assert error["code"] == "round_configuration_invalid"
    assert message in error["message"]
    assert request_api("GET", path, admin) == before
    assert sql("SELECT * FROM audit_events ORDER BY id") == audit


def test_invalid_create_does_not_write_round(
    invalid_game_config, request_api, admin, sql
):
    config, message = invalid_game_config
    sql("TRUNCATE rounds, audit_events CASCADE")
    error = request_api(
        "POST",
        "/admin/rounds",
        admin,
        {"title": "Invalid configuration", "game_config": config},
        status=409,
    )
    assert error["code"] == "round_configuration_invalid"
    assert message in error["message"]
    assert sql("SELECT id FROM rounds") == []
    assert sql("SELECT id FROM audit_events") == []


def test_snapshot_and_seed_reference_reject_invalid_config(
    invalid_game_config, api, monkeypatch
):
    config, message = invalid_game_config
    monkeypatch.setattr(seed_database, "REFERENCE_GAME_CONFIG", config)

    async def check():
        async with AsyncSessionLocal() as db:
            cards = list((await db.execute(select(ActionCard))).scalars())
            with pytest.raises(Conflict, match=message):
                freeze_game_config(config, cards)
            with pytest.raises(Conflict, match=message):
                seed_database.reference_game_config(cards)

    api.portal.call(check)
