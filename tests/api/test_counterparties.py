"""Stage-02 test configurations; resource calculation is NOT a v8 engine.

Only the autosave integration test replaces the production availability guard
and resource evaluator, within pytest monkeypatch scope. No runtime flag exists.
"""

import json
from copy import deepcopy

from tests.counterparty_support import config_v8, step
from src.aml_workshop_simulator.services.counterparties import (
    resolve_counterparty_links,
)
from src.aml_workshop_simulator.services.round_configuration import config_version


def install(sql, round_id):
    config = config_v8()
    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": round_id},
    )
    return config


def test_counterparty_autosave_replay_reload_and_catalog_snapshot(
    monkeypatch,
    request_api,
    admin,
    player,
    player_factory,
    active_round,
    command,
    sql,
    chain,
):
    # Capture a valid legacy resource DTO solely as an unrelated test double.
    path = f"/rounds/{active_round}/scenario"
    resource_fixture = request_api(
        "POST", path + "/preview", player["headers"], {"steps": chain()}
    )["resources"]
    config = install(sql, active_round)
    catalog = request_api("GET", f"/rounds/{active_round}/cards", player["headers"])
    for card in catalog:
        assert not card["context_fields"]
        assert all(f["key"] != "sender_relationship" for f in card["fields"])
        assert all(
            p["key"]
            not in {"sender_relationship", "recipient_type", "velocity", "time_of_day"}
            for p in card["visible_params"]
        )
    from src.aml_workshop_simulator.services import scenario_service

    monkeypatch.setattr(
        scenario_service, "require_playable_contract", lambda config: None
    )
    monkeypatch.setattr(
        scenario_service, "checked_snapshot", lambda *args: deepcopy(resource_fixture)
    )
    values = [step(config), step(config, "card_transfer"), step(config)]
    body = command(values)
    saved = request_api("PUT", path, player["headers"], body)
    replay = request_api("PUT", path, player["headers"], body)
    assert replay == saved
    loaded = request_api("GET", path, player["headers"])
    assert loaded["steps"] == saved["steps"]
    links = resolve_counterparty_links(loaded["steps"], config)
    assert links[1]["recipient"]["return_to_observed_sender"]
    assert links[2]["sender"]["prior_incoming_count"] == 1
    values[1]["recipient_id"] = "B"
    saved_b = request_api("PUT", path, player["headers"], command(values, 1))
    assert saved_b["revision"] == 2
    loaded = request_api("GET", path, player["headers"])
    assert loaded["steps"][1]["recipient_id"] == "B"
    assert not resolve_counterparty_links(loaded["steps"], config)[1]["recipient"][
        "return_to_observed_sender"
    ]
    other = player_factory("Второй участник")
    catalogs = [
        request_api("GET", "/rounds/current/state", p["headers"])["round"][
            "game_config"
        ]["behavior"]["counterparties"]
        for p in (player, other)
    ]
    assert catalogs[0] == catalogs[1] == config["behavior"]["counterparties"]
    before = sql("SELECT steps, revision FROM scenarios")
    for changes in [
        {"sender_id": "foreign-round"},
        {"sender_id": "shop"},
        {"action_details": {"sender_relationship": "regular_sender"}},
    ]:
        bad = deepcopy(values)
        bad[0].update(changes)
        request_api("PUT", path, player["headers"], command(bad, 2), 422)
        assert sql("SELECT steps, revision FROM scenarios") == before
    changed = deepcopy(config)
    changed.pop("card_snapshots")
    changed.pop("config_version")
    changed["behavior"]["counterparties"][0]["name"] = "Подмена"
    request_api(
        "PUT",
        f"/admin/rounds/{active_round}",
        admin,
        {"title": "Test", "expected_config_revision": 1, "game_config": changed},
        409,
    )
    assert sql("SELECT game_config FROM rounds")[0]["game_config"] == config

    # Organizer sees submitted chains only; inject status for read projection,
    # without enabling final submission/scoring of an unfinished contract.
    sql("UPDATE scenarios SET status='submitted'")
    detail = request_api(
        "GET", f"/admin/rounds/{active_round}/participants/{player['id']}", admin
    )
    assert detail["scenario"]["steps"] == loaded["steps"]


def test_real_gate_still_blocks_expanded_autosave(
    request_api, player, active_round, command, sql
):
    config = install(sql, active_round)
    error = request_api(
        "PUT",
        f"/rounds/{active_round}/scenario",
        player["headers"],
        command([step(config)]),
        409,
    )
    assert error["code"] == "round_contract_not_ready"
    assert not sql("SELECT * FROM scenarios")


def test_round_rejects_unknown_party_without_saving(
    request_api, player, active_round, command, sql
):
    config = config_v8()
    value = step(config)
    value["sender_id"] = "not-in-this-round"
    request_api(
        "PUT",
        f"/rounds/{active_round}/scenario",
        player["headers"],
        command([value]),
        422,
    )
    assert not sql("SELECT * FROM scenarios")
