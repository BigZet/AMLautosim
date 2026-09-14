from copy import deepcopy
from unittest.mock import patch
import json
import numpy as np
import pytest
from src.aml_workshop_simulator.services.model_scoring import get_model_scorer, rounded
from src.aml_workshop_simulator.schemas.scoring import ScoringExplanationOut
from src.aml_workshop_simulator.core.errors import Conflict


def sample():
    obj = json.load(open("config/model/smoke-scenario.json"))
    obj["config"]["risk_model"] = get_model_scorer().identity.copy()
    return obj["steps"], obj["config"]


def test_shap_additivity_schema_and_saved_summary():
    steps, config = sample()
    scorer = get_model_scorer()
    result = scorer.score(steps, config)
    e = result["explanation"]
    ScoringExplanationOut.model_validate(e)
    assert len(e["factors"]) == 84
    assert (
        abs(
            e["base_value"]
            + sum(f["contribution"] for f in e["factors"])
            - e["raw_score"]
        )
        < 1e-6
    )
    selected = set(e["top_positive"] + e["top_negative"])
    assert len(selected) <= 6
    assert (
        abs(
            sum(f["contribution"] for f in e["factors"] if f["code"] in selected)
            + e["remaining_contribution"]
            - sum(f["contribution"] for f in e["factors"])
        )
        < 1e-8
    )
    assert result == scorer.score(steps, config)
    assert all(f["title"] and f["description"] for f in e["factors"])


def test_model_pin_and_operation_override_rejected():
    _, config = sample()
    scorer = get_model_scorer()
    bad = deepcopy(config)
    bad["risk_model"]["model_sha256"] = "changed"
    with pytest.raises(Conflict):
        scorer.check_config(bad, require_pin=True)
    bad = deepcopy(config)
    bad["operations"][0]["energy_cost"] = 29
    with pytest.raises(Conflict):
        scorer.check_config(bad)


@pytest.mark.parametrize(
    "raw,expected", [(-2, "0.00"), (103, "100.00"), (12.345, "12.34")]
)
def test_clipping_rounding_and_shap_failure(raw, expected):
    steps, config = sample()
    scorer = get_model_scorer()
    values = np.zeros((1, 85))
    values[0, -1] = raw
    with (
        patch.object(scorer.adapter, "predict", return_value=min(100, max(0, raw))),
        patch.object(scorer.adapter.model, "predict", return_value=[raw]),
        patch.object(
            scorer.adapter.model, "get_feature_importance", return_value=values
        ),
    ):
        result = scorer.score(steps, config)
        assert str(result["risk_score"]) == expected
        e = result["explanation"]
        assert (
            abs(
                raw
                + e["clipping_adjustment"]
                + e["rounding_adjustment"]
                - float(expected)
            )
            < 1e-8
        )
        values[0, 0] = 1
        with pytest.raises(ValueError, match="additivity"):
            scorer.score(steps, config)
    assert str(rounded(12.345)) == "12.34"


def test_invalid_shap_numbers_and_dictionary_fail_closed():
    from src.aml_workshop_simulator.services.model_scoring import ModelScorer

    steps, config = sample()
    scorer = get_model_scorer()
    with patch.object(
        scorer.adapter.model,
        "get_feature_importance",
        return_value=np.full((1, 85), np.nan),
    ):
        with pytest.raises(ValueError, match="Invalid SHAP"):
            scorer.score(steps, config)
    with patch("src.aml_workshop_simulator.services.model_scoring.DICTIONARY") as file:
        file.read_text.return_value = '{"features": {}}'
        with pytest.raises(ValueError, match="dictionary"):
            ModelScorer()
