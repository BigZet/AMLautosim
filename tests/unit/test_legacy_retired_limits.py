from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services.model_scoring import ModelScorer
from src.aml_workshop_simulator.services.aml_risk_model import AMLRiskModel
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import extract_features


@pytest.mark.parametrize("retired_value", [None, 0, 999999])
def test_legacy_signature_projection_does_not_change_predictions(retired_value):
    sample = json.loads(Path("config/model/smoke-scenario.json").read_text())
    original = sample["config"]
    current = deepcopy(original)
    for key in ("max_night_operations", "max_anonymous_operations"):
        current["constraints"].pop(key, None)
        if retired_value is not None:
            current["constraints"][key] = retired_value
    current["constraints"]["category_limits"].pop("anonymous", None)
    if retired_value is not None:
        current["constraints"]["category_limits"]["anonymous"] = retired_value
    model = ModelScorer()
    archived = AMLRiskModel("resources/catboost_models/integration-v2-final")
    expected = archived.predict(sample["steps"], original)
    assert extract_features(sample["steps"], current) == extract_features(
        sample["steps"], original
    )
    assert model.adapter.predict(sample["steps"], current) == expected
    assert current != original  # adapter must not restore retired keys in caller data
    altered = deepcopy(current)
    altered["resources"]["initial_energy"] += 1
    with pytest.raises(Conflict):
        model.adapter.predict(sample["steps"], altered)
