"""Actual tiny CatBoost through API/storage; only release admission is test-only."""

from copy import deepcopy
import json

import pytest

from src.aml_workshop_simulator.services import aml_probability_model, model_scoring
from src.aml_workshop_simulator.services.round_configuration import config_version
from tests.ml.test_aml_probability_model import candidate, observations  # noqa: F401


def test_native_probability_and_shap_survive_api_storage_and_retry(
    candidate,  # noqa: F811
    observations,  # noqa: F811
    active_round,
    sql,
    monkeypatch,
    request_api,
    player,
    admin,
    command,
):
    package, _, _ = candidate
    native_factory = aml_probability_model.AMLProbabilityModel
    with pytest.raises(ValueError, match="release"):
        native_factory(package)
    # Only this tiny fixture bypasses release admission. Feature extraction,
    # native inference/SHAP, scoring dispatch, API, DB and projections are real.
    monkeypatch.setattr(
        aml_probability_model,
        "AMLProbabilityModel",
        lambda path: native_factory(path, offline_candidate=True),
    )
    monkeypatch.setenv("AML_PROBABILITY_MODEL_PATH", str(package))
    monkeypatch.setattr(
        'src.aml_workshop_simulator.services.game_classifier.get_pinned_game_classifier',
        lambda config: model_scoring._probability_scorer(str(package)),
    )
    public = deepcopy(observations[0])
    config, steps = public["config"], public["steps"]
    scorer = model_scoring.get_round_scorer(config)
    config["risk_model"] = scorer.pin_identity(config)
    config["config_version"] = config_version(config)
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"config": json.dumps(config), "id": active_round},
    )
    expected = native_factory(package, offline_candidate=True).predict(steps, config)
    submitted = request_api(
        "POST",
        f"/rounds/{active_round}/scenario/submit",
        player["headers"],
        command(steps),
    )
    assert submitted["status"] == "submitted"
    summary = request_api("POST", f"/admin/rounds/{active_round}/score", admin)
    assert summary["scored_count"] == 1
    result = request_api("GET", f"/rounds/{active_round}/result", player["headers"])
    explanation = result["explanation"]
    assert explanation == expected
    assert explanation["base_margin"] + sum(
        f["contribution"] for f in explanation["shap_values"]
    ) == pytest.approx(explanation["raw_margin"], abs=1e-6)
    stored = sql("SELECT explanation FROM scoring_results")
    assert stored == [{"explanation": expected}]
    board = request_api("GET", f"/rounds/{active_round}/leaderboard", player["headers"])
    assert board["rows"][0]["aml_probability"] == expected["aml_probability"]
    assert board["rows"][0]["category"] == expected["category"]
    # A completed score/retry must survive a unavailable runtime without changing p.
    monkeypatch.setattr(
        model_scoring,
        "get_round_scorer",
        lambda *args: pytest.fail("Completed result/retry attempted fresh inference"),
    )
    request_api("POST", f"/admin/rounds/{active_round}/score", admin)
    assert (
        request_api("GET", f"/rounds/{active_round}/result", player["headers"])
        == result
    )
    assert sql("SELECT count(*) AS n FROM scoring_results")[0]["n"] == 1
