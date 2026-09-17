import json

import numpy as np
import pytest


def test_identity_is_sigmoid_not_raw_margin_and_handles_extremes():
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    result = apply_calibrator(np.array([-1000.0, 0.0, 1000.0]), {"method": "none"})
    np.testing.assert_array_equal(result, [0, 0.5, 1])


def test_sigmoid_json_roundtrip_and_shape():
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    artifact = json.loads(json.dumps({"method": "sigmoid", "a": 2.0, "b": -1.0}))
    result = apply_calibrator(np.array([[0.0, 0.5], [1.0, 2.0]]), artifact)
    np.testing.assert_allclose(
        result,
        [[1 / (1 + np.exp(1)), 0.5], [1 / (1 + np.exp(-1)), 1 / (1 + np.exp(-3))]],
    )


def test_isotonic_is_linear_between_knots_and_clamped_at_edges():
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    artifact = {
        "method": "isotonic",
        "x": [-2.0, 0.0, 2.0],
        "y": [0.05, 0.5, 0.95],
        "interpolation": "linear_clamped",
    }
    result = apply_calibrator([-100, -1, 0, 1, 100], artifact)
    np.testing.assert_allclose(result, [0.05, 0.275, 0.5, 0.725, 0.95])


@pytest.mark.parametrize(
    "artifact",
    [
        {"method": "sigmoid", "a": 0, "b": 0},
        {"method": "sigmoid", "a": -1, "b": 0},
        {"method": "sigmoid", "a": True, "b": 0},
        {"method": "sigmoid", "a": 1, "b": float("inf")},
        {"method": "sigmoid", "a": 1},
        {"method": "isotonic", "x": [], "y": [], "interpolation": "linear_clamped"},
        {
            "method": "isotonic",
            "x": [0, 0],
            "y": [0, 1],
            "interpolation": "linear_clamped",
        },
        {
            "method": "isotonic",
            "x": [0, 1],
            "y": [1, 0],
            "interpolation": "linear_clamped",
        },
        {
            "method": "isotonic",
            "x": [0, 1],
            "y": [-0.01, 1],
            "interpolation": "linear_clamped",
        },
        {
            "method": "isotonic",
            "x": [0, 1],
            "y": [0, 1.01],
            "interpolation": "linear_clamped",
        },
        {
            "method": "isotonic",
            "x": [0, float("nan")],
            "y": [0, 1],
            "interpolation": "linear_clamped",
        },
        {"method": "isotonic", "x": [0, 1], "y": [0, 1], "interpolation": "nearest"},
        {"method": "unknown"},
        {"method": "none", "a": 2},
    ],
)
def test_invalid_artifacts_fail_closed(artifact):
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    with pytest.raises(ValueError):
        apply_calibrator([0], artifact)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_margin_is_rejected(bad):
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    with pytest.raises(ValueError):
        apply_calibrator([bad], {"method": "none"})


@pytest.mark.parametrize(
    "p,category",
    [
        (0, "low"),
        (0.09999, "low"),
        (0.1, "review"),
        (0.89999, "review"),
        (0.9, "high"),
        (1, "high"),
    ],
)
def test_probability_category_uses_unrounded_thresholds(p, category):
    from src.aml_workshop_simulator.services.aml_calibration import probability_category

    assert probability_category(p) == category


def test_offline_sigmoid_fits_positive_slope_and_lowers_loss():
    from scripts.calibrate_aml_classifier import fit_calibrator
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    # Empirical frequencies are exactly .2 and .8; raw margins overstate certainty.
    margin = np.repeat([-4.0, 4.0], 100)
    labels = np.r_[np.ones(20), np.zeros(80), np.ones(80), np.zeros(20)]
    artifact = fit_calibrator(margin, labels, "sigmoid")
    assert artifact["a"] > 0
    np.testing.assert_allclose(
        apply_calibrator([-4.0, 4.0], artifact), [0.2, 0.8], atol=1e-5
    )


def test_offline_isotonic_export_equals_reference_interpolation():
    from sklearn.isotonic import IsotonicRegression
    from scripts.calibrate_aml_classifier import fit_calibrator
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    margin = np.arange(8, dtype=float)
    labels = np.array([0, 0, 1, 0, 1, 0, 1, 1])
    artifact = fit_calibrator(margin, labels, "isotonic")
    query = np.linspace(-1, 9, 51)
    reference = IsotonicRegression(out_of_bounds="clip").fit(margin, labels)
    np.testing.assert_allclose(
        apply_calibrator(query, artifact), reference.predict(query), atol=1e-15
    )


def test_calibration_selection_blocks_group_leakage():
    from scripts.calibrate_aml_classifier import select_calibrator

    with pytest.raises(ValueError, match="group"):
        select_calibrator(
            [-1, 1],
            [0, 1],
            [-1, 1],
            [0, 1],
            fit_groups=["same", "b"],
            check_groups=["same", "c"],
            fit_observation_hashes=["x", "y"],
        )


def test_small_calibration_excludes_isotonic_before_selection():
    from scripts.calibrate_aml_classifier import select_calibrator

    _, report = select_calibrator(
        [-1, 1],
        [0, 1],
        [-1, 1],
        [1, 0],
        fit_groups=["a", "b"],
        check_groups=["c", "d"],
        fit_observation_hashes=["x", "y"],
    )
    assert report["isotonic_eligible"] is False
    assert "isotonic" not in report["candidates"]
    assert report["support_gate_passed"] is False


def test_isotonic_handles_opposite_extreme_knots_without_overflow():
    from src.aml_workshop_simulator.services.aml_calibration import apply_calibrator

    artifact = {
        "method": "isotonic",
        "x": [-1e308, 1e308],
        "y": [0, 1],
        "interpolation": "linear_clamped",
    }
    np.testing.assert_allclose(
        apply_calibrator([-1e308, 0, 1e308], artifact), [0, 0.5, 1]
    )


def test_calibration_inclusive_improvement_boundary_is_numerically_stable(monkeypatch):
    from scripts import calibrate_aml_classifier as calibration

    losses = iter(
        [{"log_loss": 0.030, "brier": 0.01}, {"log_loss": 0.028, "brier": 0.01}]
    )
    monkeypatch.setattr(calibration, "_losses", lambda y, p: next(losses))
    _, report = calibration.select_calibrator(
        [-1, 1],
        [0, 1],
        [-1, 1],
        [0, 1],
        fit_groups=["a", "b"],
        check_groups=["c", "d"],
        fit_observation_hashes=["x", "y"],
    )
    assert report["selected"] == "sigmoid"


def test_calibration_cli_refuses_overwrite_before_model_access(tmp_path):
    from scripts.calibrate_aml_classifier import calibrate

    with pytest.raises(FileExistsError):
        calibrate(
            tmp_path / "dataset", tmp_path / "model", tmp_path / "protocol", tmp_path
        )


def test_calibration_cli_requires_audited_dataset_before_loading_model(
    tmp_path, monkeypatch
):
    from scripts import calibrate_aml_classifier as calibration

    monkeypatch.setattr(
        calibration, "audit_dataset", lambda path: {"release_ready": False}
    )
    with pytest.raises(ValueError, match="release-ready"):
        calibration.calibrate(
            tmp_path / "dataset",
            tmp_path / "model",
            tmp_path / "protocol",
            tmp_path / "output",
        )
    assert not (tmp_path / "output").exists()
