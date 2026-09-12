from src.aml_workshop_simulator.domain.round_policy import CARD_OVERRIDE_KEYS


def test_editor_metadata_requires_admin_and_matches_contract(
    request_api, admin, player
):
    path = "/admin/game-config/editor-metadata"
    request_api("GET", path, status=401)
    request_api("GET", path, player["headers"], status=403)
    data = request_api("GET", path, admin)
    assert "max_visible_params" not in data["limits"]
    assert {r["key"] for r in data["overrides"]} == set(CARD_OVERRIDE_KEYS)
    fee = next(r for r in data["overrides"] if r["key"] == "fee_rate")
    assert fee["decimal_places"] == 6 and fee["maximum"] == "1"
    assert data["supported_versions"]["ruleset_version"]


def test_semantic_error_has_operation_path(request_api, admin, round_id):
    config = request_api("GET", "/admin/game-config/default", admin)
    config["operations"][0]["visible_params"] = ["action.nonexistent"]
    error = request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {"game_config": config, "expected_config_revision": 1},
        409,
    )
    assert error["code"] == "round_configuration_invalid"
    assert (
        error["details"]["violations"][0]["field"]
        == "game_config.operations.0.visible_params"
    )
