"""Real resource engine/HTTP/PostgreSQL; only launch guards are isolated in tests."""

import pytest

import json
from copy import deepcopy

from tests.counterparty_support import config_v8, FIXTURES
from src.aml_workshop_simulator.services.round_configuration import config_version


def test_preview_save_submit_replay_share_timeline(
    monkeypatch, request_api, admin, player, active_round, command, sql
):
    from src.aml_workshop_simulator.services import scenario_service, scenarios

    monkeypatch.setattr(scenario_service, "require_playable_contract", lambda _: None)
    monkeypatch.setattr(scenarios, "require_playable_contract", lambda _: None)
    config = config_v8()
    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    golden = json.loads((FIXTURES / "legacy-v7.json").read_text())
    values = deepcopy(
        next(c for c in golden["cases"] if c["name"] == "incoming_funding")["steps"]
    )
    for item in values:
        code = item["card"]["code"]
        item["context"] = {k: v for k, v in item["context"].items() if k == "channel"}
        item["action_details"].pop("sender_relationship", None)
        item.update(
            sender_id="A"
            if code == "incoming_transfer"
            else "employer"
            if code == "salary"
            else None,
            recipient_id="A" if code == "card_transfer" else None,
            interval_minutes=1,
        )
    values[0]["interval_minutes"] = 1440  # discarded on the first step, no waiting cost
    values[1]["interval_minutes"] = 10
    path = f"/rounds/{active_round}/scenario"
    preview = request_api(
        "POST", path + "/preview", player["headers"], {"steps": values}
    )
    assert preview["can_submit"]
    saved = request_api("PUT", path, player["headers"], command(values))
    assert saved["resources"] == preview["resources"]
    assert saved["steps"][0]["interval_minutes"] is None
    read = request_api("GET", path, player["headers"])
    assert read["resources"] == preview["resources"]
    submitted_body = command(values, 1)
    submitted = request_api("POST", path + "/submit", player["headers"], submitted_body)
    assert submitted["resources"] == preview["resources"]
    assert (
        request_api("POST", path + "/submit", player["headers"], submitted_body)
        == submitted
    )
    stored = sql("SELECT steps,resource_snapshot FROM scenarios")[0]
    from src.aml_workshop_simulator.schemas.game_state import ResourceSnapshotOut

    assert (
        ResourceSnapshotOut.model_validate(stored["resource_snapshot"]).model_dump(
            mode="json"
        )
        == preview["resources"]
    )
    assert (
        stored["resource_snapshot"]["resources_after"]
        == preview["resources"]["resources_after"]
    )
    assert "occurred_at" not in str(stored["steps"])
    # Production start and score guards were never replaced.
    assert (
        request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin, status=409)[
            "code"
        ]
        == "round_contract_not_ready"
    )


def test_external_v8_preview_stays_blocked(request_api, player, active_round, sql):
    config = config_v8()
    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    error = request_api(
        "POST",
        f"/rounds/{active_round}/scenario/preview",
        player["headers"],
        {"steps": []},
        409,
    )
    assert error["code"] == "round_contract_not_ready"


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
