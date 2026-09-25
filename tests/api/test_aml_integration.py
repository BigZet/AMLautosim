"""Read/retry compatibility for schema-4 results using an explicitly test-only scorer."""

import json

import pytest

from src.aml_workshop_simulator.services import model_scoring
from tests.aml_context_support import context_fixture
from tests.unit.test_aml_backend_dispatch import probability_scorer  # noqa: F401
from tests.unit.test_aml_result_ui import aml_explanation  # noqa: F401


@pytest.fixture
def installed_aml_round(active_round, sql, monkeypatch, probability_scorer):  # noqa: F811
    config, steps = context_fixture()
    config["risk_model"] = probability_scorer.pin_identity(config)
    from src.aml_workshop_simulator.services.round_configuration import config_version

    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    monkeypatch.setenv("AML_PROBABILITY_MODEL_PATH", "test-package")
    monkeypatch.setattr(
        'src.aml_workshop_simulator.services.game_classifier.get_pinned_game_classifier',
        lambda config: probability_scorer,
    )
    return active_round, config, steps


def test_probability_atomic_retry_storage_and_completed_reads(
    request_api,
    admin,
    player_factory,
    command,
    sql,
    installed_aml_round,
    probability_scorer,  # noqa: F811
    monkeypatch,  # noqa: F811
):
    round_id, config, steps = installed_aml_round
    players = [player_factory("First"), player_factory("Second")]
    for player in players:
        request_api(
            "POST",
            f"/rounds/{round_id}/scenario/submit",
            player["headers"],
            command(steps),
        )
    original = probability_scorer.score
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("test interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(probability_scorer, "score", fail_second)
    request_api("POST", f"/admin/rounds/{round_id}/score", admin, status=500)
    assert sql("SELECT * FROM scoring_results") == []
    assert [r["status"] for r in sql("SELECT status FROM scenarios")] == [
        "submitted",
        "submitted",
    ]
    # A process restart may leave scoring status persisted; the existing lock/retry protocol recovers it.
    sql("UPDATE rounds SET status='scoring'")
    monkeypatch.setattr(probability_scorer, "score", original)
    summary = request_api("POST", f"/admin/rounds/{round_id}/score", admin)
    assert summary["leaderboard_version"] == "leaderboard-aml-probability-v1"
    stored = sql("SELECT * FROM scoring_results ORDER BY id")
    assert len(stored) == 2
    assert stored[0]["explanation"]["aml_probability"] == 0.09999
    assert str(stored[0]["risk_score"]) == "10.00"
    assert stored[0]["risk_label"] == "normal"
    assert (
        stored[0]["explanation"]["model_identity"]["package_sha256"]
        == config["risk_model"]["package_sha256"]
    )
    assert (
        stored[0]["explanation"]["context_sha256"]
        == config["risk_model"]["context_sha256"]
    )

    def unavailable(*args, **kwargs):
        raise AssertionError("saved result must not load a model")

    monkeypatch.setattr(model_scoring, "get_round_scorer", unavailable)
    monkeypatch.setattr(model_scoring, "get_model_scorer", unavailable)
    for player in players:
        state = request_api("GET", "/rounds/current/state", player["headers"])
        assert state["result"]["explanation"]["aml_probability"] == 0.09999
        assert state["result"]["explanation"]["category"] == "low"
        assert state["result"]["scores"]["risk_score"] == "10.00"
        board = request_api("GET", f"/rounds/{round_id}/leaderboard", player["headers"])
        assert all(row["aml_probability"] == 0.09999 and row["category"] == "low"
                   and row["score_kind"] == "aml_probability" for row in board["rows"])
    admin_board = request_api("GET", f"/admin/rounds/{round_id}/leaderboard", admin)
    assert all(row["aml_probability"] == 0.09999 and row["category"] == "low"
               and row["leaderboard_version"] == "leaderboard-aml-probability-v1"
               for row in admin_board["rows"])
    request_api("POST", f"/admin/rounds/{round_id}/score", admin)
    assert len(sql("SELECT * FROM scoring_results")) == 2


def test_modified_pin_fails_atomically(
    request_api, admin, player, command, sql, installed_aml_round
):
    round_id, config, steps = installed_aml_round
    request_api(
        "POST", f"/rounds/{round_id}/scenario/submit", player["headers"], command(steps)
    )
    config["risk_model"]["calibration_sha256"] = "0" * 64
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb)",
        {"config": json.dumps(config)},
    )
    error = request_api("POST", f"/admin/rounds/{round_id}/score", admin, status=409)
    assert error["code"] == "model_version_mismatch"
    assert sql("SELECT * FROM scoring_results") == []
