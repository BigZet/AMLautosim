"""New contract through the UI HTTP client, plus saved-round compatibility."""

import json
from pathlib import Path
from uuid import uuid4

from scripts.seed_database import seed
from src.aml_workshop_simulator.ui.shared.api_client import SimulatorAPIClient


def test_incoming_card_preview_save_submit_and_score(
    api, request_api, player, admin, active_round, chain
):
    client = SimulatorAPIClient()
    client._client.close()
    client._client = api
    cards = client.get_round_cards(active_round)
    assert {c["code"] for c in cards} == {
        "salary",
        "incoming_transfer",
        "card_transfer",
        "cash_withdrawal",
    }
    incoming = next(c for c in cards if c["code"] == "incoming_transfer")
    assert [p["key"] for p in incoming["visible_params"]] == [
        "transfer_source",
        "sender_relationship",
    ]
    assert incoming["channels"] == ["bank"] and incoming["quota_category"] is None
    steps = chain()
    for step in steps:
        if step["card"]["code"] == "incoming_transfer":
            step["action_details"] = {
                "transfer_source": "crypto_exchange",
                "sender_relationship": "anonymous_established_account",
            }
    sid = player["headers"]["X-Session-ID"]
    preview = client.preview_scenario(active_round, steps, sid)
    assert preview["can_submit"]
    assert preview["resources"]["limit_usage"]["cash"] == "10000.00"
    saved = client.put_scenario(active_round, steps, 0, sid, str(uuid4()))
    assert saved["resources"] == preview["resources"]
    assert client.get_scenario(active_round, sid)["steps"] == saved["steps"]
    assert all(
        s["context"]["channel"] == "bank"
        for s in saved["steps"]
        if s["card"]["code"] == "incoming_transfer"
    )
    submitted = client.submit_scenario(
        active_round, saved["steps"], saved["revision"], sid, str(uuid4())
    )
    assert submitted["status"] == "submitted"
    request_api("POST", f"/admin/rounds/{active_round}/score", admin)
    result = client.get_result(active_round, sid)
    assert result is not None


def test_seed_replaces_catalog_but_keeps_legacy_round_playable(
    api, request_api, player, admin, active_round, sql
):
    # A real previous card snapshot, independent of the live catalog and its fields.
    legacy = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/legacy_cash_deposit_snapshot.json"
        ).read_text()
    )
    config = sql("SELECT game_config FROM rounds WHERE id=:id", {"id": active_round})[
        0
    ]["game_config"]
    current = next(
        c for c in config["card_snapshots"] if c["code"] == "incoming_transfer"
    )
    legacy["id"] = current["id"]
    config["card_snapshots"] = [
        legacy if c["code"] == "incoming_transfer" else c
        for c in config["card_snapshots"]
    ]
    config["constraints"]["category_limits"]["cash"] = "240000.00"
    for operation in config["operations"]:
        if operation["code"] == "incoming_transfer":
            operation.update(
                code="cash_deposit", visible_params=legacy["default_visible_params"]
            )
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    sql(
        "UPDATE action_cards SET code='cash_deposit' WHERE id=:id", {"id": legacy["id"]}
    )
    step = {
        "step_id": str(uuid4()),
        "card": {"id": legacy["id"], "code": "cash_deposit", "version": 1},
        "amount": "80000.00",
        "context": {"channel": "atm"},
        "action_details": {"funds_source": "documented_savings"},
    }
    path = f"/rounds/{active_round}/scenario"
    before = request_api(
        "PUT",
        path,
        player["headers"],
        {"steps": [step], "expected_revision": 0, "client_mutation_id": str(uuid4())},
    )
    assert before["resources"]["valid"]
    api.portal.call(seed)
    assert (
        sql("SELECT game_config FROM rounds WHERE id=:id", {"id": active_round})[0][
            "game_config"
        ]
        == config
    )
    assert {c["code"] for c in sql("SELECT code FROM action_cards")} == {
        "salary",
        "incoming_transfer",
        "card_transfer",
        "cash_withdrawal",
    }
    cards = request_api("GET", f"/rounds/{active_round}/cards")
    assert "cash_deposit" in {c["code"] for c in cards}
    after = request_api(
        "POST", path + "/preview", player["headers"], {"steps": before["steps"]}
    )
    assert after["resources"] == before["resources"]
    assert after["resources"]["limit_usage"]["cash"] == "80000.00"
    assert request_api("GET", path, player["headers"]) == before
    fresh = request_api(
        "POST", f"/admin/rounds/{active_round}/restart", admin, status=201
    )
    assert {c["code"] for c in request_api("GET", f"/rounds/{fresh['id']}/cards")} == {
        "salary",
        "incoming_transfer",
        "card_transfer",
        "cash_withdrawal",
    }
