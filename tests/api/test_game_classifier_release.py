import json
import os
import pytest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
from src.aml_workshop_simulator.ui.nicegui.shap_result import aml_result_view_model

EXAMPLES = json.loads(
    (Path(__file__).parents[1] / "fixtures/attribute_context_examples.json").read_text(
        encoding="utf-8"
    )
)
BASELINE = json.loads((Path(__file__).parents[1] / "fixtures/retired_limits_baseline.json").read_bytes())
for example, row in zip(EXAMPLES, BASELINE["rows"], strict=True):
    example["steps"] = row["steps"]
    example["probability"] = row["probability"]



@pytest.fixture
def seeded_game_version():
    return 10


def test_incompatible_purpose_cannot_be_saved_or_submitted(
    request_api, player, active_round, chain, command
):
    steps = chain()
    next(s for s in steps if s["card"]["code"] == "incoming_transfer")[
        "purpose_code"
    ] = "salary"
    path = f"/rounds/{active_round}/scenario"
    for method, suffix, body in [
        ("POST", "/preview", {"steps": steps}),
        ("PUT", "", command(steps)),
        ("POST", "/submit", command(steps)),
    ]:
        reply = request_api(method, path + suffix, player["headers"], body, status=422)
        assert "Назначение не соответствует" in str(reply)


def test_v10_parallel_edits_have_one_winner(api, player, active_round, chain, command):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    commands = [command(chain()), command(chain())]

    def save(payload):
        barrier.wait(timeout=10)
        return api.put(
            f"/api/v1/rounds/{active_round}/scenario",
            headers=player["headers"],
            json=payload,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(save, commands))
    assert sorted(r.status_code for r in replies) == [200, 409]
    saved = api.get(
        f"/api/v1/rounds/{active_round}/scenario", headers=player["headers"]
    )
    assert saved.status_code == 200 and saved.json()["revision"] == 1


def test_published_examples_end_to_end(
    request_api, admin, round_id, player_factory, command, sql
):
    config = request_api("GET", "/admin/rounds/current", admin)["game_config"]
    assert config["schema_version"] == 10
    assert config["risk_model"] == get_game_classifier().identity
    request_api("POST", f"/admin/rounds/{round_id}/start", admin)
    cards = {(c["code"], c["version"]): c["id"] for c in config["card_snapshots"]}
    players = []
    for example in EXAMPLES:
        player = player_factory(example["scenario_id"])
        steps = deepcopy(example["steps"])
        for step in steps:
            step["card"]["id"] = cards[(step["card"]["code"], step["card"]["version"])]
        path = f"/rounds/{round_id}/scenario"
        preview = request_api(
            "POST", path + "/preview", player["headers"], {"steps": steps}
        )
        assert "explanation" not in str(preview)
        request_api("PUT", path, player["headers"], command(steps))
        request_api("PUT", path, player["headers"], command(steps), 409)
        request_api("POST", path + "/submit", player["headers"], command(steps, 1))
        assert (
            request_api("GET", "/rounds/current/state", player["headers"])["result"]
            is None
        )
        request_api(
            "POST", f"/admin/rounds/{round_id}/score?wait=true", player["headers"], status=403
        )
        players.append(player)
    scorer = get_game_classifier()
    original = scorer.score
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Injected scoring failure")
        return original(*args, **kwargs)

    with patch.object(type(scorer), "score", side_effect=fail_second):
        request_api("POST", f"/admin/rounds/{round_id}/score?wait=true", admin, status=500)
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 0
    request_api("POST", f"/admin/rounds/{round_id}/score?wait=true", admin)
    saved_results = []
    for player, example in zip(players, EXAMPLES):
        result = request_api("GET", "/rounds/current/state", player["headers"])[
            "result"
        ]
        exp = result["explanation"]
        assert exp["schema_version"] == 5
        assert abs(exp["aml_probability"] - example["probability"]) <= 1e-10
        assert len(exp["windows"]) == 3
        assert (
            aml_result_view_model(exp)["score_kind"]
            == "educational_pattern_probability"
        )
        assert (
            request_api("GET", "/rounds/current/state", player["headers"])["result"]
            == result
        )
        saved_results.append({"scenario_id": example["scenario_id"], "result": result})
    board = request_api(
        "GET", f"/rounds/{round_id}/leaderboard", players[0]["headers"]
    )["rows"]
    assert len(board) == 25
    assert all(row["score_kind"] == "educational_pattern_probability" for row in board)
    with patch.object(
        type(scorer), "score", side_effect=AssertionError("must not recalculate")
    ):
        request_api("POST", f"/admin/rounds/{round_id}/score?wait=true", admin)
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 25
    if os.environ.get("AML_PLAYTEST_RESULTS_OUTPUT"):
        Path(os.environ["AML_PLAYTEST_RESULTS_OUTPUT"]).write_text(
            json.dumps(saved_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def test_fixed_context_limits_and_package_failure(
    request_api, admin, round_id, monkeypatch, tmp_path
):
    default = request_api("GET", "/admin/game-config/default", admin)
    assert default["schema_version"] == 10
    changed = deepcopy(default)
    changed["behavior"]["timeline"]["starts_at"] = "2027-01-01T10:00:00+03:00"
    request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {"expected_config_revision": 1, "game_config": changed},
        422,
    )
    monkeypatch.setenv("AML_PROBABILITY_MODEL_PATH", str(tmp_path / "missing"))
    request_api("POST", f"/admin/rounds/{round_id}/start", admin, status=409)


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
