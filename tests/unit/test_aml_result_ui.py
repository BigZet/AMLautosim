"""Saved v3/v4 result contracts and the actual NiceGUI rendering path."""

import asyncio
from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from src.aml_workshop_simulator.schemas import scoring
from src.aml_workshop_simulator.ui.nicegui import shap_result as renderer


@pytest.fixture
def aml_explanation():
    # Hand-authored DTO fixture; no claim of a released model or API acceptance.
    return {
        "schema_version": 4,
        "score_kind": "aml_probability",
        "aml_probability": 0.09999,
        "uncalibrated_probability": 0.5,
        "raw_margin": 0.0,
        "risk_score": 9.999,
        "category": "low",
        "context_status": "partial",
        "context_sha256": "a" * 64,
        "model_identity": {
            "package_sha256": "b" * 64,
            "model_sha256": "c" * 64,
            "calibration_sha256": "d" * 64,
            "schema_sha256": "e" * 64,
            "thresholds_sha256": "f" * 64,
            "contract_version": 10,
            "extractor_version": "aml-observable-v5.0",
        },
        "explanation_space": "raw_margin",
        "base_margin": -0.25,
        "shap_residual": 0.0,
        "shap_values": [
            {
                "feature": "unknown_share",
                "value": 0.5,
                "contribution": 0.25,
                "title": "Неподтверждённая сумма",
                "description": "Доля суммы без применимого основания.",
            }
        ],
        "calibration": {
            "parameters": {"method": "isotonic", "x": [-1.0, 1.0], "y": [0.0, 0.19998]},
            "input_space": "raw_margin",
            "output_space": "probability",
        },
    }


@pytest.fixture
def legacy_explanation():
    return {
        "schema_version": 3,
        "method": "catboost-tree-shap",
        "model": {"model_sha256": "a" * 64},
        "reference": "training",
        "base_value": 30.0,
        "raw_score": 32.0,
        "normalized_score": "32.00",
        "clipping_adjustment": 0.0,
        "rounding_adjustment": 0.0,
        "additivity_error": 0.0,
        "factors": [
            {
                "code": "transfers",
                "title": "Переводы",
                "description": "Число переводов.",
                "unit": "шт.",
                "value": 2,
                "display_value": "2",
                "contribution": 2.0,
            }
        ],
        "top_positive": ["transfers"],
        "top_negative": [],
        "remaining_contribution": 0.0,
        "disclaimer": "Учебная оценка риска.",
    }


@pytest.mark.parametrize(
    "probability,category",
    [
        (0.09999, "low"),
        (0.1, "review"),
        (0.89999, "review"),
        (0.9, "high"),
    ],
)
def test_probability_category_uses_unrounded_value(
    aml_explanation, probability, category
):
    assert hasattr(renderer, "aml_result_view_model"), "AML view-model missing"
    aml_explanation.update(
        aml_probability=probability, risk_score=100 * probability, category=category
    )
    view = renderer.aml_result_view_model(aml_explanation)
    assert view["category"] == category
    assert view["score_kind"] == "aml_probability"
    assert view["probability_text"] == ("10,0%" if probability < 0.5 else "90,0%")
    assert view["context_status"] == "partial"


@pytest.mark.parametrize(
    "probability,category,text",
    [
        (0, "low", "<0,1%"),
        (0.00099, "low", "<0,1%"),
        (0.001, "low", "0,1%"),
        (0.999, "high", "99,9%"),
        (0.99901, "high", ">99,9%"),
        (1, "high", ">99,9%"),
    ],
)
def test_probability_edge_display(aml_explanation, probability, category, text):
    assert hasattr(renderer, "aml_result_view_model"), "AML view-model missing"
    aml_explanation.update(
        aml_probability=probability, risk_score=100 * probability, category=category
    )
    assert renderer.aml_result_view_model(aml_explanation)["probability_text"] == text


def test_discriminated_dto_roundtrip_preserves_probability_and_legacy(
    aml_explanation, legacy_explanation
):
    assert hasattr(scoring, "PublishedScoringExplanationOut"), "v3/v4 union missing"
    adapter = TypeAdapter(scoring.PublishedScoringExplanationOut)
    aml = adapter.validate_python(aml_explanation)
    legacy = adapter.validate_python(legacy_explanation)
    assert isinstance(aml, scoring.AMLProbabilityExplanationOut)
    assert isinstance(legacy, scoring.ScoringExplanationOut)
    assert (
        adapter.validate_json(adapter.dump_json(aml)).model_dump(exclude_none=True)
        == aml_explanation
    )
    assert (
        adapter.validate_json(adapter.dump_json(legacy)).model_dump()
        == legacy_explanation
    )
    assert (
        scoring.ScoringExplanationOut.model_validate(
            legacy_explanation
        ).normalized_score
        == "32.00"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 5),
        ("score_kind", "regression"),
        ("aml_probability", float("nan")),
        ("aml_probability", 1.1),
        ("category", "review"),
        ("risk_score", 10.0),
        ("context_status", "confident"),
        ("explanation_space", "probability"),
    ],
)
def test_dto_rejects_invalid_or_inconsistent_aml_result(aml_explanation, field, value):
    assert hasattr(scoring, "PublishedScoringExplanationOut"), "v3/v4 union missing"
    aml_explanation[field] = value
    with pytest.raises(ValidationError):
        TypeAdapter(scoring.PublishedScoringExplanationOut).validate_python(
            aml_explanation
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"method": "unknown"},
        {"method": "sigmoid", "a": float("nan"), "b": 0},
        {"method": "isotonic", "x": [-1, 1], "y": [0, float("inf")]},
    ],
)
def test_dto_rejects_invalid_calibration_descriptor(aml_explanation, parameters):
    aml_explanation["calibration"]["parameters"] = parameters
    with pytest.raises(ValidationError):
        TypeAdapter(scoring.PublishedScoringExplanationOut).validate_python(
            aml_explanation
        )


@pytest.mark.parametrize(
    "parameters,logit",
    [
        ({"method": "none"}, None),
        ({"method": "sigmoid", "a": 1.2, "b": -0.1}, -0.1),
    ],
)
def test_dto_roundtrip_keeps_calibration_method(aml_explanation, parameters, logit):
    aml_explanation["calibration"]["parameters"] = parameters
    if logit is not None:
        aml_explanation["calibration"]["calibrated_logit"] = logit
    adapter = TypeAdapter(scoring.PublishedScoringExplanationOut)
    result = adapter.validate_json(
        adapter.dump_json(adapter.validate_python(aml_explanation))
    )
    assert (
        result.model_dump(exclude_none=True)["calibration"]
        == aml_explanation["calibration"]
    )


def test_mounted_shap_result_renders_v4_margin_and_context(
    aml_explanation, tmp_path, monkeypatch
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")

    async def run():
        async with user_simulation() as user:

            @ui.page("/aml-explanation")
            def page():
                renderer.shap_result(aml_explanation, expanded=True)

            await user.open("/aml-explanation")
            for text in [
                "Вероятность AML-сценария в учебной модели",
                "10,0%",
                "Низкая вероятность",
                "Контекст: частичный",
                "Неподтверждённая сумма",
                "+0,250000 raw margin",
                "не доказательство",
                "не причинный эффект",
            ]:
                await user.should_see(text)
            for text in ["AML исключён", "балла", "Итоговый риск"]:
                await user.should_not_see(text)

    asyncio.run(run())


def test_mounted_shap_result_preserves_legacy_points(
    legacy_explanation, tmp_path, monkeypatch
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    saved = deepcopy(legacy_explanation)

    async def run():
        async with user_simulation() as user:

            @ui.page("/legacy-explanation")
            def page():
                renderer.shap_result(legacy_explanation, expanded=True)

            await user.open("/legacy-explanation")
            await user.should_see("Итоговый риск: 32,00 / 100")
            await user.should_see("+2,00 балла")
            await user.should_not_see("Вероятность AML-сценария в учебной модели")
            await user.should_not_see("32,0%")

    asyncio.run(run())
    assert legacy_explanation == saved


@pytest.mark.parametrize(
    "probability,category,title",
    [
        (0.09999, "low", "Низкая вероятность"),
        (0.9, "high", "Высокая вероятность"),
    ],
)
def test_mounted_participant_metric_uses_probability(
    aml_explanation, probability, category, title, tmp_path, monkeypatch
):
    from scripts.check_expanded_balance import demo_config
    from src.aml_workshop_simulator.services.expanded_simulation import (
        evaluate_expanded_scenario,
    )
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import result_panel

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    aml_explanation.update(
        aml_probability=probability, risk_score=100 * probability, category=category
    )
    result = {
        "explanation": aml_explanation,
        "scores": {
            "game_score": "50",
            "resource_score": "20",
            "risk_score": "10.00",
            "risk_label": "review",
        },
        "resources": evaluate_expanded_scenario([], demo_config()),
        "rank": 1,
    }

    async def run():
        async with user_simulation() as user:

            @ui.page("/aml-participant")
            def page():
                result_panel(result)

            await user.open("/aml-participant")
            await user.should_see(title)
            await user.should_not_see("10,00 / 100")
            await user.should_not_see("Оценка достигла порога проверки.")
            await user.should_not_see("Обычный риск")

    asyncio.run(run())
