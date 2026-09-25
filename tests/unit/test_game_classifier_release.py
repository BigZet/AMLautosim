from copy import deepcopy
import json
import math
from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.schemas.scoring import GamePatternExplanationOut
from src.aml_workshop_simulator.services.game_classifier import (
    DEFAULT_PACKAGE,
    get_game_classifier,
)


@pytest.fixture
def example():
    runtime = get_game_classifier()
    steps = json.loads(
        (Path(__file__).parents[1] / "fixtures/game_classifier_chain.json").read_text(
            encoding="utf-8"
        )
    )
    return runtime.predict(steps, {**runtime.context, "risk_model": runtime.identity})


@pytest.mark.parametrize(
    "probability, category",
    [(0.099999, "low"), (0.1, "review"), (0.899999, "review"), (0.9, "high")],
)
def test_categories_before_rounding(example, probability, category):
    value = deepcopy(example)
    margin = math.log(probability / (1 - probability))
    value.update(
        aml_probability=probability,
        uncalibrated_probability=probability,
        risk_score=probability * 100,
        category=category,
    )
    value["calibration"]["parameters"] = {"method": "none"}
    for window in value["windows"]:
        window.update(
            probability=probability,
            raw_margin=margin,
            base_margin=margin,
            shap_residual=0,
        )
        for factor in window["shap_values"]:
            factor["contribution"] = 0
    GamePatternExplanationOut.model_validate(value)
    value["category"] = "high" if category != "high" else "low"
    with pytest.raises(ValidationError):
        GamePatternExplanationOut.model_validate(value)


@pytest.mark.parametrize(
    "filename",
    ["model.cbm", "context.json", "features.json", "manifest.json", "release.json"],
)
def test_package_corruption_fails_closed(tmp_path, monkeypatch, filename):
    package = tmp_path / "package"
    shutil.copytree(DEFAULT_PACKAGE, package)
    monkeypatch.setenv("AML_PROBABILITY_MODEL_PATH", str(package))
    get_game_classifier()
    with (package / filename).open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(Conflict) as error:
        get_game_classifier()
    assert error.value.code == "model_unavailable"


def test_pin_is_immutable_and_organizer_history_is_supported():
    runtime = get_game_classifier()
    config = deepcopy(runtime.context)
    config["risk_model"] = runtime.identity
    runtime.check_config(config, require_pin=True)
    config["risk_model"] = {**runtime.identity, "model_version": "other"}
    with pytest.raises(Conflict):
        runtime.check_config(config, require_pin=True)
    config = deepcopy(runtime.context)
    config["behavior"]["history"]["operations"][0]["amount"] = "123.00"
    runtime.check_config(config)


def test_individual_window_shap_is_validated(example):
    value = deepcopy(example)
    value["windows"][0]["shap_values"][0]["contribution"] += 1
    with pytest.raises(ValidationError):
        GamePatternExplanationOut.model_validate(value)


def test_game_explanation_is_collapsed_until_requested(example, tmp_path, monkeypatch):
    import asyncio
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.shap_result import shap_result

    monkeypatch.setattr(Storage, "path", tmp_path / "ui")

    async def run():
        async with user_simulation() as user:

            @ui.page("/collapsed-explanation")
            def page():
                shap_result(example)

            await user.open("/collapsed-explanation")
            panel = next(
                e
                for e in user.find(ui.expansion).elements
                if e.text == "Что повлияло на оценку"
            )
            assert panel.value is False
            with user:
                panel.open()
            assert panel.value is True
            assert any(table.rows for table in user.find(ui.table).elements)

    asyncio.run(run())
