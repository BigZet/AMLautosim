"""Tests run only in the isolated requirements-ml environment."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from catboost import CatBoostRegressor, Pool

from scripts.catboost_pipeline import (
    choose_candidate,
    frame_for_model,
    gate,
    measure,
    metrics,
)


def test_gate_exact_boundaries_and_asymmetry():
    y = np.full(20, 75.0)
    prediction = y.copy()
    prediction[0] = 59
    result = metrics(y, prediction)
    assert result["high_under_15_count"] == 1
    assert result["high_under_15_rate"] == 0.05
    assert gate(result, 10)["passed"]
    prediction[1] = 59
    assert not gate(metrics(y, prediction), 10)["passed"]
    prediction[:] = 75
    prediction[0] = 49.9
    assert not gate(metrics(y, prediction), 10)["checks"]["no_high_below_50"]
    prediction[0] = 50
    assert gate(metrics(y, prediction), 10)["checks"]["no_high_below_50"]
    prediction[0] = 60
    assert metrics(y, prediction)["high_under_15_count"] == 0
    assert not gate(metrics([10, 20], [10, 20]), 5)["passed"]


def test_report_clipping_without_hiding_raw_errors():
    result = measure([0, 100], [-10, 110], 50)
    assert result["raw"]["mae"] == 10
    assert result["clipped"]["mae"] == 0
    assert result["clipped_count"] == 2


def candidate(name, mae, trees, passed, dangerous=0, under=0.01):
    return {
        "id": name,
        "trees": trees,
        "validation": {
            "gate": {"passed": passed},
            "clipped": {
                "mae": mae,
                "high_below_50_count": dangerous,
                "high_under_15_rate": under,
            },
        },
    }


def test_selection_honors_gates_and_diagnostic_priority():
    accurate_unsafe = candidate("unsafe", 1, 10, False, dangerous=1)
    safe = candidate("safe", 4, 100, True)
    tied = candidate("tied", 4, 50, True)
    assert choose_candidate([accurate_unsafe, safe, tied])["id"] == "tied"
    a = candidate("a", 9, 50, False, under=0.1)
    b = candidate("b", 6, 50, False, under=0.2)
    assert choose_candidate([accurate_unsafe, a, b])["id"] == "a"
    before = deepcopy([accurate_unsafe, safe])
    choose_candidate(before)
    assert before == [accurate_unsafe, safe]


def test_schema_names_reordering_extras_and_missing_values():
    x = pd.DataFrame({"number": [1, 2], "income_basis": ["absent", "payroll"]})
    columns = list(x.columns)
    assert frame_for_model(x[columns[::-1]], columns).equals(x)
    assert list(frame_for_model(x.assign(target_risk_score=99), columns)) == columns
    with pytest.raises(ValueError, match="Missing required features"):
        frame_for_model(x.drop(columns="number"), columns)
    with pytest.raises(ValueError, match="Nonfinite"):
        frame_for_model(x.assign(number=np.inf), columns)
    with pytest.raises(ValueError, match="Missing feature"):
        frame_for_model(x.assign(income_basis=None), columns)
    with pytest.raises(ValueError, match="Duplicate"):
        frame_for_model(pd.concat([x, x], axis=1), columns)


def test_real_model_serialization_and_reordering(tmp_path):
    x = pd.DataFrame({"amount": range(20), "income_basis": ["absent", "payroll"] * 10})
    y = np.arange(20) * 2
    pool = Pool(x, y, cat_features=["income_basis"])
    model = CatBoostRegressor(
        iterations=8,
        depth=2,
        thread_count=1,
        random_seed=12,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(pool)
    expected = model.predict(x)
    model.save_model(str(tmp_path / "model.cbm"))
    loaded = CatBoostRegressor()
    loaded.load_model(str(tmp_path / "model.cbm"))
    reordered = frame_for_model(x[list(reversed(x.columns))], list(x.columns))
    np.testing.assert_allclose(expected, loaded.predict(reordered), rtol=0, atol=1e-8)


def test_loaded_model_feature_importance_is_calculated(tmp_path):
    x = pd.DataFrame({"value": range(30)})
    model = CatBoostRegressor(
        iterations=5, depth=2, verbose=False, thread_count=1, allow_writing_files=False
    )
    model.fit(x, np.arange(30) * 2)
    model.save_model(str(tmp_path / "model.cbm"))
    loaded = CatBoostRegressor()
    loaded.load_model(str(tmp_path / "model.cbm"))
    importance = loaded.get_feature_importance(
        type="PredictionValuesChange", thread_count=1
    )
    assert len(importance) == 1 and np.isfinite(importance).all()


def test_slices_distinguish_absent_groups_from_zero_error():
    from scripts.catboost_pipeline import slice_metrics

    x = pd.DataFrame(
        {
            "history_known": [0],
            "history_empty": [0],
            "income_basis": ["absent"],
            "count_purchase": [0],
            "count_cash_withdrawal": [0],
            "interval_max": [1],
        }
    )
    rows = slice_metrics(x, np.array([75.0]), np.array([75.0]))
    payroll = next(
        row
        for row in rows
        if row["dimension"] == "salary" and row["value"] == "payroll_registry"
    )
    assert payroll["n"] == 0 and "mae" not in payroll
    absent = next(
        row for row in rows if row["dimension"] == "salary" and row["value"] == "absent"
    )
    assert absent["n"] == 1 and absent["mae"] == 0
