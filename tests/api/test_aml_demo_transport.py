"""Real demo DTO/engine/storage path; fixture scores are NOT model acceptance."""

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.create_aml_demo import (
    check_result,
    input_config,
    server_steps,
    server_explanation,
)
from src.aml_workshop_simulator.api.routers.admin import rounds as router
from src.aml_workshop_simulator.services import admin_rounds, model_scoring
from tests.unit.test_aml_backend_dispatch import probability_scorer  # noqa: F401
from tests.unit.test_aml_result_ui import aml_explanation  # noqa: F401


@pytest.mark.parametrize("game_index", range(5))
def test_frozen_demo_survives_real_creation_submit_storage_and_retry(
    game_index,
    probability_scorer,  # noqa: F811
    api,
    sql,
    monkeypatch,
    request_api,
    admin,
    player_factory,
):
    # Both overrides are isolated in this fixture. Public release remains closed.
    monkeypatch.setattr(router, "require_new_round_allowed", lambda config: None)
    monkeypatch.setattr(admin_rounds, "require_new_round_allowed", lambda config: None)
    monkeypatch.setattr(
        model_scoring, "get_round_scorer", lambda config: probability_scorer
    )
    # Only the disposable test database is cleared, to exercise POST /rounds.
    sql("TRUNCATE rounds RESTART IDENTITY CASCADE")
    game = json.loads(
        Path("resources/aml_dataset/aml-v1/demo-frozen/v2/casebook.json").read_bytes()
    )["rounds"][game_index]
    public = game["cases"][0]["record"]["public_snapshot"]
    created = request_api(
        "POST",
        "/admin/rounds",
        admin,
        {"title": game["title"], "game_config": input_config(public["config"])},
        status=201,
    )
    rid, saved = created["id"], created["game_config"]
    assert saved["risk_model"] == probability_scorer.pin_identity(saved)
    request_api("POST", f"/admin/rounds/{rid}/start", admin)
    players = []
    for case in game["cases"]:
        row = case["record"]
        player = player_factory()
        steps = server_steps(row["public_snapshot"], saved)
        submitted = request_api(
            "POST",
            f"/rounds/{rid}/scenario/submit",
            player["headers"],
            {
                "steps": steps,
                "expected_revision": 0,
                "client_mutation_id": str(uuid4()),
            },
        )
        assert submitted["status"] == "submitted"
        players.append((row, player, submitted["id"], steps))
    summary = request_api("POST", f"/admin/rounds/{rid}/score", admin)
    assert summary["submitted_count"] == summary["scored_count"] == 5
    assert request_api("POST", f"/admin/rounds/{rid}/score", admin) == summary
    for row, player, scenario_id, steps in players:
        original = deepcopy(row["public_snapshot"])
        expected = probability_scorer.adapter.predict(**original)
        expected = server_explanation(expected, original["config"], saved)
        result = request_api("GET", f"/rounds/{rid}/result", player["headers"])
        assert (
            check_result(
                result, expected, scenario_id=scenario_id, steps=steps, config=saved
            )
            == expected["aml_probability"]
        )
        if row is players[0][0]:
            for malformed in (
                {"explanation": result["explanation"]},
                {**result, "scenario_id": scenario_id + 999},
                {**result, "scores": {**result["scores"], "risk_score": "99.00"}},
                {**result, "scores": {**result["scores"], "game_score": "1.00"}},
                {
                    **result,
                    "resources": {
                        **result["resources"],
                        "resources_after": {
                            **result["resources"]["resources_after"],
                            "balance": "999999.00",
                        },
                    },
                },
            ):
                with pytest.raises(ValueError):
                    check_result(
                        malformed,
                        expected,
                        scenario_id=scenario_id,
                        steps=steps,
                        config=saved,
                    )
        assert request_api("GET", f"/rounds/{rid}/result", player["headers"]) == result
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 5
