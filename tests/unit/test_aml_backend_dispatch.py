from copy import deepcopy
from decimal import Decimal

import pytest

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services import model_scoring
from src.aml_workshop_simulator.domain import scoring
from src.aml_workshop_simulator.domain.contract_versions import (
    require_new_round_allowed,
)
from tests.aml_context_support import context_fixture
from tests.unit.test_aml_result_ui import aml_explanation  # noqa: F401


@pytest.fixture
def probability_scorer(monkeypatch, aml_explanation):  # noqa: F811
    from src.aml_workshop_simulator.services import aml_probability_model

    class Runtime:
        model_identity = deepcopy(aml_explanation["model_identity"])

        def __init__(self, package):
            pass

        def check_config(self, config):
            aml_probability_model.validate_config(config)

        def predict(self, steps, config):
            result = deepcopy(aml_explanation)
            result["context_sha256"] = aml_probability_model.canonical_hash(
                config["behavior"]
            )
            return result

    monkeypatch.setattr(aml_probability_model, "AMLProbabilityModel", Runtime)
    assert hasattr(model_scoring, "ProbabilityScorer"), "missing classifier adapter"
    return model_scoring.ProbabilityScorer("test-package")


def test_dispatch_rejects_v9_and_missing_classifier(monkeypatch, tmp_path):
    assert hasattr(model_scoring, "get_round_scorer"), "missing contract dispatch"
    monkeypatch.setenv("AML_PROBABILITY_MODEL_PATH", str(tmp_path / "missing"))
    for version in (9, 10):
        with pytest.raises(Conflict):
            model_scoring.get_round_scorer({"schema_version": version})
    assert (
        model_scoring.get_round_scorer({"schema_version": 8})
        is model_scoring.get_model_scorer()
    )


def test_v10_creation_uses_released_classifier():
    from src.aml_workshop_simulator.services.game_classifier import game_config

    require_new_round_allowed(game_config())


@pytest.mark.parametrize(
    "field",
    [
        "package_sha256",
        "model_sha256",
        "calibration_sha256",
        "schema_sha256",
        "thresholds_sha256",
        "score_kind",
        "context_sha256",
    ],
)
def test_exact_pin_and_context_immutable(probability_scorer, field):
    config, steps = context_fixture()
    config["risk_model"] = probability_scorer.pin_identity(config)
    probability_scorer.score(steps, config)
    config["risk_model"][field] = "changed"
    with pytest.raises(Conflict):
        probability_scorer.score(steps, config)


def test_context_forgery_cannot_reuse_pin(probability_scorer):
    config, steps = context_fixture()
    config["risk_model"] = probability_scorer.pin_identity(config)
    config["behavior"]["aml_context"]["facts"][0]["verification_status"] = (
        "contradicted"
    )
    with pytest.raises(Conflict):
        probability_scorer.score(steps, config)


@pytest.mark.parametrize(
    "p,category,label",
    [
        (0.09999, "low", "normal"),
        (0.1, "review", "review"),
        (0.89999, "review", "review"),
        (0.9, "high", "suspicious"),
    ],
)
def test_probability_preserved_category_unrounded(
    probability_scorer,
    aml_explanation,  # noqa: F811
    p,
    category,
    label,  # noqa: F811
):  # noqa: F811
    aml_explanation.update(aml_probability=p, risk_score=100 * p, category=category)
    config, steps = context_fixture()
    config["risk_model"] = probability_scorer.pin_identity(config)
    result = probability_scorer.score(steps, config)
    assert result["explanation"]["aml_probability"] == p
    assert result["risk_score"] == Decimal("10.00" if p < 0.5 else "90.00")
    assert result["risk_label"] == label


def test_leaderboard_uses_probability_before_rounding():
    assert hasattr(scoring, "probability_leaderboard_scores"), (
        "missing probability leaderboard"
    )
    config = {"leaderboard": {"weights": {"stealth": "0.7", "resources": "0.3"}}}
    result = scoring.probability_leaderboard_scores(0.09995, Decimal("0"), config)
    assert result == {
        "stealth_score": Decimal("90.00"),
        "resource_score": Decimal("0"),
        "game_score": Decimal("63.00"),
    }
    result = scoring.probability_leaderboard_scores(0.09996, Decimal("0.01"), config)
    assert result["game_score"] == Decimal("63.01")


def test_nonrelease_package_cannot_enter_online_dispatch(monkeypatch, tmp_path):
    import json

    package = tmp_path / "candidate"
    package.mkdir()
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "version": "aml-probability-package-v1",
                "task": "binary_classification",
                "positive_class": 1,
                "classes": [0, 1],
                "score_kind": "aml_probability",
                "contract_version": 10,
                "extractor_version": "aml-observable-v5.0",
                "release_ready": False,
                "status": "pending-evaluation",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AML_PROBABILITY_MODEL_PATH", str(package))
    with pytest.raises(Conflict) as exc:
        model_scoring.get_round_scorer({"schema_version": 10})
    assert exc.value.code == "model_unavailable"


def test_runtime_cannot_replace_pinned_model_identity(
    probability_scorer,
    aml_explanation,  # noqa: F811
):  # noqa: F811
    config, steps = context_fixture()
    config["risk_model"] = probability_scorer.pin_identity(config)
    probability_scorer.adapter.model_identity["model_sha256"] = "0" * 64
    aml_explanation["model_identity"]["model_sha256"] = "0" * 64
    with pytest.raises(Conflict):
        probability_scorer.score(steps, config)
