import json

from tests.counterparty_support import step
from tests.purchase_support import purchase_config
from scripts.check_expanded_balance import demo_steps
from src.aml_workshop_simulator.services.round_configuration import config_version


def test_freeze_preview_save_submit_score_and_result(
    monkeypatch, api, request_api, admin, player, active_round, command, sql
):
    original = sql("SELECT game_config FROM rounds")[0]["game_config"]
    frozen = request_api("GET", "/admin/rounds/current", admin)["game_config"]
    catalog = request_api("GET", f"/rounds/{active_round}/cards")
    assert next(c for c in catalog if c["code"] == "purchase")["max_occurrences"] == 3
    path = f"/rounds/{active_round}/scenario"
    values = demo_steps(frozen, "purchase")
    preview = request_api(
        "POST", path + "/preview", player["headers"], {"steps": values}
    )
    assert preview["can_submit"]
    totals = preview["resources"]["totals"]
    assert (
        totals["gross_outflow"] == "401000.00"
        and totals["target_outflow"] == "400000.00"
    )
    saved = request_api("PUT", path, player["headers"], command(values))
    assert saved["resources"] == preview["resources"]
    assert (
        request_api("GET", path, player["headers"])["resources"] == preview["resources"]
    )
    submitted = request_api(
        "POST", path + "/submit", player["headers"], command(values, 1)
    )
    assert submitted["resources"] == preview["resources"]
    request_api("POST", f"/admin/rounds/{active_round}/score", admin)
    state = request_api("GET", "/rounds/current/state", player["headers"])
    assert state["result"]["resources"] == preview["resources"]
    assert (
        state["result"]["resources"]["per_step"][-1]["purchase"]["category"]
        == "groceries"
    )
    scored = sql("SELECT scoring_version FROM scoring_results")[0]
    assert scored["scoring_version"] == frozen["risk_model"]["model_version"]
    assert sql("SELECT game_config FROM rounds")[0]["game_config"] == original


def test_only_purchases_cannot_submit_and_limits_are_visible(
    monkeypatch, request_api, player, active_round, command, sql
):
    from src.aml_workshop_simulator.services import scenario_service, scenarios

    for module in (scenario_service, scenarios):
        monkeypatch.setattr(module, "require_playable_contract", lambda _: None)
    config = purchase_config()
    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    values = [step(config, "purchase", "shop")]
    path = f"/rounds/{active_round}/scenario"
    result = request_api(
        "POST", path + "/preview", player["headers"], {"steps": values}
    )
    assert not result["can_submit"]
    assert (
        next(
            b for b in result["blockers"] if b["reason"] == "target_outflow_not_reached"
        )["current"]
        == "0.00"
    )
    request_api("POST", path + "/submit", player["headers"], command(values), 400)
    assert not sql("SELECT * FROM scenarios")


def test_duplicate_purchase_configuration_is_rejected(request_api, admin, round_id):
    config = request_api("GET", "/admin/game-config/default", admin)
    config["operations"].append(
        {"code": "purchase", "version": 1, "visible_params": []}
    )
    request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {"title": "Test", "expected_config_revision": 1, "game_config": config},
        422,
    )
    assert "purchase" in [
        c["code"] for c in request_api("GET", f"/rounds/{round_id}/cards")
    ]
