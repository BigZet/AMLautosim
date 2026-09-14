"""Offline CatBoost experiment. No imports or writes to the running game API."""

import hashlib
import json
import platform
import shutil
import subprocess
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

VERSION = "aml-catboost-experiment-v1"
FEATURE_VERSION = "aml-observable-v2.6"
TARGET = "target_risk_score"
CATEGORICAL = ["income_basis"]
EXPECTED_SPLITS = {"train": 13195, "validation": 2934, "test": 3871}
GROUP_SPLITS = {
    "five-transfers": "train",
    "six-transfers": "validation",
    "eight-transfers": "test",
}
GATES = {
    "mae_max": 5,
    "high_min": 75,
    "under_by": 15,
    "under_rate_max": 0.05,
    "danger_below": 50,
}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def sha(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def frame_for_model(frame, columns):
    if frame.columns.duplicated().any():
        raise ValueError("Duplicate feature columns")
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required features: {sorted(missing)}")
    result = frame.loc[:, columns].copy()
    if result.isna().any().any():
        raise ValueError("Missing feature values")
    for key in columns:
        if key in CATEGORICAL:
            if (
                not result[key]
                .map(lambda value: isinstance(value, str) and bool(value))
                .all()
            ):
                raise ValueError(f"Invalid categorical feature: {key}")
        else:
            result[key] = pd.to_numeric(result[key], errors="raise")
            if not np.isfinite(result[key].to_numpy(dtype=float)).all():
                raise ValueError(f"Nonfinite feature: {key}")
    return result


def load_dataset(directory):
    directory = Path(directory)
    checksums = read(directory / "CHECKSUMS.json")
    required = {
        "scenarios.jsonl",
        "features.csv",
        "split.csv",
        "manifest.json",
        "feature-schema.json",
        "rubric.json",
    }
    if not required <= set(checksums):
        raise ValueError("Incomplete dataset checksum manifest")
    for name, expected in checksums.items():
        if Path(name).name != name or sha(directory / name) != expected:
            raise ValueError(f"Dataset checksum mismatch: {name}")
    manifest = read(directory / "manifest.json")
    schema = read(directory / "feature-schema.json")
    if (
        manifest["stage"] != "release"
        or manifest["extractor"] != FEATURE_VERSION
        or schema["version"] != FEATURE_VERSION
    ):
        raise ValueError("Unsupported release or extractor")
    if (
        manifest["generator"] != "expanded-review-v2-final-1"
        or read(directory / "rubric.json")["version"] != "educational-risk-v2-final-1"
    ):
        raise ValueError("Unsupported dataset version")
    columns = schema["columns"]
    if len(set(columns)) != len(columns) or TARGET in columns:
        raise ValueError("Invalid feature schema")
    frame = pd.read_csv(directory / "features.csv", keep_default_na=False)
    if list(frame.columns) != columns + [TARGET]:
        raise ValueError("CSV columns differ from the frozen schema")
    x = frame_for_model(frame, columns)
    y = pd.to_numeric(frame[TARGET], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(y).all() or ((y < 0) | (y > 100)).any():
        raise ValueError("Invalid targets")
    split = pd.read_csv(directory / "split.csv", keep_default_na=False)
    if len(x) != 20000 or len(split) != len(x) or manifest["count"] != len(x):
        raise ValueError("Unexpected row count")
    if not np.array_equal(split.row_index, np.arange(len(x))) or not split.id.is_unique:
        raise ValueError("Invalid split row identity")
    if split.split.value_counts().to_dict() != EXPECTED_SPLITS:
        raise ValueError("Frozen split counts changed")
    if not split.group.map(GROUP_SPLITS).equals(split.split):
        raise ValueError("Related groups cross partitions")
    return {
        "directory": directory,
        "x": x,
        "y": y,
        "split": split,
        "columns": columns,
        "checksums": checksums,
        "manifest": manifest,
    }


def verify_raw_features(data):
    from src.aml_workshop_simulator.services.aml_dataset_features_v2 import (
        extract_features,
    )

    count = 0
    expected_rows = data["x"].to_dict("records")
    seen = set()
    with (data["directory"] / "scenarios.jsonl").open() as file:
        for i, line in enumerate(file):
            row = json.loads(line)
            if i >= len(data["x"]):
                raise ValueError("Unexpected raw record")
            split = data["split"].iloc[i]
            if (
                row["id"] != split.id
                or row["group"] != split.group
                or row[TARGET] != data["y"][i]
            ):
                raise ValueError(f"Raw identity/target mismatch at row {i}")
            if row["observable_hash"] in seen:
                raise ValueError("Duplicate observable chain")
            seen.add(row["observable_hash"])
            computed = extract_features(row["steps"], row["config_snapshot"])
            for key in data["columns"]:
                actual, expected = computed[key], expected_rows[i][key]
                if key in CATEGORICAL:
                    equal = actual == expected
                else:
                    equal = np.isclose(
                        float(actual), float(expected), rtol=0, atol=1e-8
                    )
                if not equal:
                    raise ValueError(f"Extractor mismatch at row {i}: {key}")
            count += 1
            if count % 2000 == 0:
                print(f"raw features verified: {count}/20000", flush=True)
    if count != len(data["x"]):
        raise ValueError("Missing raw records")
    return {
        "status": "passed",
        "rows": count,
        "extractor": FEATURE_VERSION,
        "absolute_tolerance": 1e-8,
    }


def metrics(y, prediction):
    y, prediction = np.asarray(y, dtype=float), np.asarray(prediction, dtype=float)
    if not len(y) or len(y) != len(prediction) or not np.isfinite(prediction).all():
        raise ValueError("Invalid metric input")
    error = prediction - y
    high = y >= GATES["high_min"]
    n_high = int(high.sum())
    under = int(((error < -GATES["under_by"]) & high).sum())
    danger = int(((prediction < GATES["danger_below"]) & high).sum())
    return {
        "n": len(y),
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "median_abs_error": float(np.median(np.abs(error))),
        "p90_abs_error": float(np.quantile(np.abs(error), 0.9)),
        "bias_prediction_minus_target": float(error.mean()),
        "high_n": n_high,
        "high_under_15_count": under,
        "high_under_15_rate": under / n_high if n_high else None,
        "high_below_50_count": danger,
    }


def gate(result, baseline_mae):
    checks = {
        "mae": result["mae"] <= GATES["mae_max"],
        "high_under_rate": result["high_n"] > 0
        and result["high_under_15_rate"] <= GATES["under_rate_max"],
        "no_high_below_50": result["high_n"] > 0 and result["high_below_50_count"] == 0,
        "beats_train_median": result["mae"] < baseline_mae,
    }
    return {"passed": all(checks.values()), "checks": checks}


def measure(y, prediction, baseline_mae):
    prediction = np.asarray(prediction, dtype=float)
    raw = metrics(y, prediction)
    clipped = metrics(y, np.clip(prediction, 0, 100))
    return {
        "raw": raw,
        "clipped": clipped,
        "gate": gate(clipped, baseline_mae),
        "clipped_count": int(((prediction < 0) | (prediction > 100)).sum()),
    }


def choose_candidate(candidates):
    passed = [row for row in candidates if row["validation"]["gate"]["passed"]]
    if passed:
        return min(
            passed,
            key=lambda row: (
                row["validation"]["clipped"]["mae"],
                row["trees"],
                row["id"],
            ),
        )
    return min(
        candidates,
        key=lambda row: (
            row["validation"]["clipped"]["high_below_50_count"],
            row["validation"]["clipped"]["high_under_15_rate"],
            row["validation"]["clipped"]["mae"],
            row["trees"],
            row["id"],
        ),
    )


def fit_one(params, train_pool, validation_pool):
    model = CatBoostRegressor(**params)
    model.fit(
        train_pool,
        eval_set=validation_pool,
        early_stopping_rounds=100,
        use_best_model=True,
        verbose=False,
    )
    return model


def train(directory, output, seed=20260914):
    output = Path(output)
    if output.exists():
        raise ValueError(
            "Training output must be new; existing experiment is immutable"
        )
    data = load_dataset(directory)
    output.mkdir(parents=True)
    shutil.copyfile(__file__, output / "training-pipeline.py")
    write(output / "input-checksums.json", data["checksums"])
    write(
        output / "feature-schema.json",
        {
            "version": FEATURE_VERSION,
            "columns": data["columns"],
            "categorical": CATEGORICAL,
        },
    )
    write(output / "raw-feature-check.json", verify_raw_features(data))
    (output / "environment.txt").write_text(
        subprocess.check_output(["python", "-m", "pip", "freeze"], text=True)
    )
    write(
        output / "environment.json",
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pipeline": VERSION,
            "pipeline_sha256": sha(__file__),
        },
    )
    masks = {
        name: (data["split"].split == name).to_numpy()
        for name in ("train", "validation")
    }
    pools = {
        name: Pool(data["x"].loc[mask], data["y"][mask], cat_features=CATEGORICAL)
        for name, mask in masks.items()
    }
    y_valid = data["y"][masks["validation"]]
    median = float(np.median(data["y"][masks["train"]]))
    baseline = metrics(y_valid, np.full(len(y_valid), median))
    write(
        output / "validation-baseline.json",
        {"train_median": median, "metrics": baseline},
    )
    candidates = []
    (output / "candidates").mkdir()
    for i, (depth, l2, loss) in enumerate(
        product((4, 6, 8), (3, 10), ("RMSE", "Quantile:alpha=0.65")), 1
    ):
        params = dict(
            iterations=2000,
            learning_rate=0.05,
            depth=depth,
            l2_leaf_reg=l2,
            loss_function=loss,
            eval_metric="MAE",
            random_seed=seed,
            thread_count=4,
            task_type="CPU",
            allow_writing_files=False,
        )
        start = time.monotonic()
        model = fit_one(params, pools["train"], pools["validation"])
        prediction = model.predict(pools["validation"])
        identity = f"candidate-{i:02d}"
        model.save_model(str(output / "candidates" / f"{identity}.cbm"))
        row = {
            "id": identity,
            "params": params,
            "trees": model.tree_count_,
            "seconds": time.monotonic() - start,
            "validation": measure(y_valid, prediction, baseline["mae"]),
        }
        candidates.append(row)
        write(output / "experiments.json", candidates)
        write(
            output / "candidates" / f"{identity}-history.json", model.get_evals_result()
        )
        print(
            f"{identity}: depth={depth} l2={l2} {loss}; MAE={row['validation']['clipped']['mae']:.4f}; gate={row['validation']['gate']['passed']}; trees={model.tree_count_}",
            flush=True,
        )
    selected = choose_candidate(candidates)
    # Selection is committed before any test predictions are made.
    write(
        output / "selection.json",
        {
            "pipeline": VERSION,
            "selected": selected,
            "seed": seed,
            "train_median": median,
            "test_used_for_selection": False,
            "refit_train_validation": False,
            "gates": GATES,
        },
    )
    shutil.copyfile(
        output / "candidates" / f"{selected['id']}.cbm", output / "model.cbm"
    )
    write(output / "model-checksum.json", {"sha256": sha(output / "model.cbm")})
    main = CatBoostRegressor()
    main.load_model(str(output / "model.cbm"))
    expected = main.predict(pools["validation"])
    stability = []
    for other_seed in (seed + 1, seed + 2):
        model = fit_one(
            {**selected["params"], "random_seed": other_seed},
            pools["train"],
            pools["validation"],
        )
        stability.append(
            {
                "seed": other_seed,
                "trees": model.tree_count_,
                "validation": measure(
                    y_valid, model.predict(pools["validation"]), baseline["mae"]
                ),
            }
        )
        print(
            f"stability seed {other_seed}: MAE={stability[-1]['validation']['clipped']['mae']:.4f}",
            flush=True,
        )
    write(output / "stability.json", stability)
    repeated = fit_one(selected["params"], pools["train"], pools["validation"])
    delta = float(np.max(np.abs(repeated.predict(pools["validation"]) - expected)))
    repeated.save_model(str(output / "reproduced.cbm"))
    loaded = CatBoostRegressor()
    loaded.load_model(str(output / "reproduced.cbm"))
    reload_delta = float(
        np.max(
            np.abs(
                loaded.predict(pools["validation"])
                - repeated.predict(pools["validation"])
            )
        )
    )
    shuffled = frame_for_model(
        data["x"].loc[masks["validation"], list(reversed(data["columns"]))],
        data["columns"],
    )
    reorder_delta = float(np.max(np.abs(main.predict(shuffled) - expected)))
    missing_rejected = False
    try:
        frame_for_model(shuffled.drop(columns=data["columns"][0]), data["columns"])
    except ValueError:
        missing_rejected = True
    verification = {
        "repeat_max_abs_diff": delta,
        "reload_max_abs_diff": reload_delta,
        "reorder_max_abs_diff": reorder_delta,
        "missing_feature_rejected": missing_rejected,
        "tolerance": 1e-8,
    }
    verification["passed"] = (
        max(delta, reload_delta, reorder_delta) <= 1e-8 and missing_rejected
    )
    write(output / "reproducibility.json", verification)
    if not verification["passed"]:
        raise ValueError(f"Reproducibility failed: {verification}")
    print(
        f"TRAIN COMPLETE: {selected['id']}; validation gate={selected['validation']['gate']['passed']}; repeat delta={delta}",
        flush=True,
    )


def slice_metrics(x, y, prediction):
    groups = {
        "risk_band": pd.cut(
            y,
            [-1, 25, 50, 75, 101],
            right=False,
            labels=["0-24", "25-49", "50-74", "75-100"],
        ).astype(str),
        "history": np.where(
            x.history_known == 0,
            "unknown",
            np.where(x.history_empty == 1, "observed_empty", "observed_activity"),
        ),
        "salary": x.income_basis,
        "purchases": np.where(x.count_purchase > 0, "present", "absent"),
        "cash": np.where(x.count_cash_withdrawal > 0, "present", "absent"),
        "interval_max": x.interval_max.astype(str),
    }
    rows = []
    expected_levels = {
        "risk_band": ["0-24", "25-49", "50-74", "75-100"],
        "salary": ["absent", "no_reference", "payroll_registry", "service_contract"],
        "history": ["unknown", "observed_empty", "observed_activity"],
        "purchases": ["present", "absent"],
        "cash": ["present", "absent"],
    }
    for dimension, values in groups.items():
        values = np.asarray(values)
        for value in sorted(set(values) | set(expected_levels.get(dimension, []))):
            mask = values == value
            if not mask.any():
                rows.append(
                    {
                        "dimension": dimension,
                        "value": value,
                        "n": 0,
                        "note": "not represented; metrics undefined",
                    }
                )
                continue
            rows.append(
                {
                    "dimension": dimension,
                    "value": value,
                    **metrics(y[mask], prediction[mask]),
                }
            )
    return rows


def pair_diagnostics(model, columns, directory):
    from src.aml_workshop_simulator.services.aml_dataset_features_v2 import (
        extract_features,
    )

    rows = []
    with (Path(directory) / "pairs.jsonl").open() as file:
        for line in file:
            pair = json.loads(line)
            predicted, targets = {}, {}
            for side in ("before", "after"):
                record = pair[side]
                features = extract_features(record["steps"], record["config_snapshot"])
                prediction = model.predict(
                    frame_for_model(pd.DataFrame([features]), columns)
                )[0]
                predicted[side] = float(np.clip(prediction, 0, 100))
                targets[side] = record[TARGET]
            delta = predicted["after"] - predicted["before"]
            expectation = pair["expectation"]
            consistent = (
                abs(delta) <= 1
                if expectation == "equal"
                else delta >= -1
                if expectation == "increase"
                else delta <= 1
            )
            rows.append(
                {
                    "kind": pair["kind"],
                    "expected": expectation,
                    "rubric": targets,
                    "prediction": predicted,
                    "predicted_delta": delta,
                    "rubric_delta": targets["after"] - targets["before"],
                    "consistent_within_1_point": consistent,
                }
            )
    return rows


def plots(output, y, prediction, importance):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False}
    )
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].hexbin(y, prediction, gridsize=35, mincnt=1, cmap="Blues")
    axes[0].plot([0, 100], [0, 100], "--", color="#a33")
    axes[0].set(
        xlabel="Rubric score",
        ylabel="Prediction",
        xlim=(0, 100),
        ylim=(0, 100),
        title="Held-out test",
    )
    axes[1].hist(prediction - y, bins=40, color="#2864a0")
    axes[1].axvline(0, color="#a33", linestyle="--")
    axes[1].set(
        xlabel="Prediction minus rubric",
        ylabel="Scenarios",
        title="Negative error = underestimation",
    )
    fig.tight_layout()
    fig.savefig(output / "test-errors.png")
    plt.close(fig)
    top = importance.head(20).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.barh(top.feature, top.importance, color="#2864a0")
    ax.set(
        xlabel="PredictionValuesChange importance",
        title="Top 20 features (not causal effects)",
    )
    fig.tight_layout()
    fig.savefig(output / "feature-importance.png")
    plt.close(fig)


def evaluate(directory, model_directory, output, pairs_directory):
    """Only load and predict. Never fit or change the selected model."""
    model_directory, output = Path(model_directory), Path(output)
    if output.exists():
        raise ValueError("Evaluation output must be new")
    data = load_dataset(directory)
    if read(model_directory / "input-checksums.json") != data["checksums"]:
        raise ValueError("Evaluation dataset differs from training")
    schema = read(model_directory / "feature-schema.json")
    if schema["columns"] != data["columns"] or schema["version"] != FEATURE_VERSION:
        raise ValueError("Model schema mismatch")
    if read(model_directory / "model-checksum.json")["sha256"] != sha(
        model_directory / "model.cbm"
    ):
        raise ValueError("Model checksum mismatch")
    selection = read(model_directory / "selection.json")
    if selection["test_used_for_selection"] or selection["refit_train_validation"]:
        raise ValueError("Invalid experiment protocol")
    model = CatBoostRegressor()
    model.load_model(str(model_directory / "model.cbm"))
    if model.feature_names_ != data["columns"]:
        raise ValueError("Model feature names mismatch")
    output.mkdir(parents=True)
    write(
        output / "evaluation-code.json",
        {
            "pipeline_sha256": sha(__file__),
            "model_sha256": sha(model_directory / "model.cbm"),
            "training_performed": False,
        },
    )
    all_predictions = model.predict(data["x"])
    results, slices = {}, []
    for name in ("train", "validation", "test"):
        mask = (data["split"].split == name).to_numpy()
        y, pred = data["y"][mask], all_predictions[mask]
        baseline = metrics(y, np.full(len(y), selection["train_median"]))
        results[name] = {
            **measure(y, pred, baseline["mae"]),
            "median_baseline": baseline,
        }
        for view, values in (("raw", pred), ("clipped", np.clip(pred, 0, 100))):
            slices.extend(
                {"split": name, "view": view, **row}
                for row in slice_metrics(data["x"].loc[mask], y, values)
            )
    if (
        results["validation"]["clipped"]
        != selection["selected"]["validation"]["clipped"]
    ):
        raise ValueError("Saved model does not reproduce selection metrics")
    predictions = data["split"].copy()
    predictions[TARGET] = data["y"]
    predictions["prediction_raw"] = all_predictions
    predictions["prediction"] = np.clip(all_predictions, 0, 100)
    predictions["error"] = predictions.prediction - predictions[TARGET]
    predictions.to_csv(output / "predictions.csv", index=False)
    pd.DataFrame(slices).to_csv(output / "slices.csv", index=False)
    # Baseline and explanations are read only after the selected model is frozen.
    baseline_predictions, details = [], {}
    test_rows = predictions[predictions.split == "test"]
    extreme_indices = set(test_rows.nsmallest(20, "error").index) | set(
        test_rows.nlargest(20, "error").index
    )
    with (data["directory"] / "scenarios.jsonl").open() as file:
        for i, line in enumerate(file):
            record = json.loads(line)
            baseline_predictions.append(float(record["baseline"]["risk_score"]))
            if i in extreme_indices:
                details[i] = {
                    "id": record["id"],
                    "family": record["family"],
                    "explanation": record["explanation"],
                    "steps": record["steps"],
                    "config_snapshot": record["config_snapshot"],
                }
    baseline_predictions = np.asarray(baseline_predictions, dtype=float)
    for name in results:
        mask = (data["split"].split == name).to_numpy()
        results[name]["deterministic_baseline"] = metrics(
            data["y"][mask], baseline_predictions[mask]
        )
    examples = []
    for direction, indices in (
        ("under", test_rows.nsmallest(20, "error").index),
        ("over", test_rows.nlargest(20, "error").index),
    ):
        for i in indices:
            examples.append(
                {"direction": direction, **predictions.loc[i].to_dict(), **details[i]}
            )
    write(output / "largest-errors.json", examples)
    pairs = pair_diagnostics(model, data["columns"], pairs_directory)
    write(
        output / "pairs.json",
        {
            "independent_test": False,
            "sign_tolerance": 1,
            "pairs": pairs,
            "input_sha256": sha(Path(pairs_directory) / "pairs.jsonl"),
        },
    )
    importance = pd.DataFrame(
        {
            "feature": model.feature_names_,
            "importance": model.get_feature_importance(
                type="PredictionValuesChange", thread_count=4
            ),
        }
    ).sort_values("importance", ascending=False)
    importance.to_csv(output / "feature-importance.csv", index=False)
    test_mask = (data["split"].split == "test").to_numpy()
    plots(
        output,
        data["y"][test_mask],
        np.clip(all_predictions[test_mask], 0, 100),
        importance,
    )
    reproducible = read(model_directory / "reproducibility.json")["passed"]
    ready = (
        results["validation"]["gate"]["passed"]
        and results["test"]["gate"]["passed"]
        and reproducible
    )
    status = (
        "готова к отдельному этапу интеграции"
        if ready
        else "эксперимент завершён, критерии не пройдены"
    )
    write(
        output / "metrics.json",
        {
            "status": status,
            "gates": GATES,
            "splits": results,
            "evaluation_trains_model": False,
        },
    )
    report(output, model_directory, selection, results, status, pairs)
    write(
        output / "CHECKSUMS.json",
        {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()},
    )
    print(
        f"EVALUATION COMPLETE: {status}; test MAE={results['test']['clipped']['mae']:.4f}",
        flush=True,
    )
    return results


def report(output, model_directory, selection, results, status, pairs):
    lines = [
        "# Первая модель учебного AML-риска",
        "",
        f"Статус: **{status}**.",
        "",
        "Модель не подключена к игре. Цель — воспроизведение синтетической рубрики, не вероятность банковского обнаружения.",
        "",
        "## Протокол",
        "",
        f"Release v2-1; extractor {FEATURE_VERSION}; CatBoost 1.2.10, CPU, Python 3.13. Seed {selection['seed']}.",
        f"Выбрана {selection['selected']['id']}: `{selection['selected']['params']}`; деревьев {selection['selected']['trees']}.",
        "",
        "12 конфигураций сравнивались только на validation. Test открыт после фиксации selection.json; переобучение на train+validation не выполнялось.",
        "",
        "## Метрики после ограничения 0–100",
        "",
        "| Часть | N | MAE | RMSE | P90 ошибки | Высокий риск | Занижение >15 | Высокий риск → <50 | MAE медианы | MAE прежнего скоринга |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in results.items():
        m = result["clipped"]
        lines.append(
            f"| {name} | {m['n']} | {m['mae']:.3f} | {m['rmse']:.3f} | {m['p90_abs_error']:.3f} | {m['high_n']} | {m['high_under_15_count']} ({m['high_under_15_rate']:.2%}) | {m['high_below_50_count']} | {result['median_baseline']['mae']:.3f} | {result['deterministic_baseline']['mae']:.3f} |"
        )
    lines += [
        "",
        "Полные метрики до/после ограничения, медиана ошибки и смещение: [metrics.json](metrics.json). Разрезы с числом примеров: [slices.csv](slices.csv).",
        "",
        "![Ошибки test](test-errors.png)",
        "",
        "![Важность признаков](feature-importance.png)",
        "",
        "## Проверки и ограничения",
        "",
        f"Проверка сохранения, перестановки колонок и повторного обучения: `{read(model_directory / 'reproducibility.json')}`.",
        "",
        "Два дополнительных seed оценены только на validation; они не заменяют основную модель. Результаты и критерии:",
        "",
    ]
    for row in read(model_directory / "stability.json"):
        lines.append(
            f"- Seed {row['seed']}: MAE {row['validation']['clipped']['mae']:.3f}, критерии {'пройдены' if row['validation']['gate']['passed'] else 'не пройдены'}."
        )
    lines += [
        "",
        "Парные проверки — известные диагностические примеры, не независимый test. Допуск направления/равенства — 1 балл; отклонения не скрываются.",
        "",
        "| Изменение | Ожидание | Δ рубрики | Δ модели | Направление в допуске |",
        "|---|---|---:|---:|---|",
    ]
    for row in pairs:
        lines.append(
            f"| {row['kind']} | {row['expected']} | {row['rubric_delta']:.3f} | {row['predicted_delta']:.3f} | {row['consistent_within_1_point']} |"
        )
    lines += [
        "",
        "Крупнейшие ошибки с исходными цепочками и объяснениями: [largest-errors.json](largest-errors.json).",
        "",
        "Только три группы шаблонов: пять исходящих переводов в train, шесть в validation и восемь в test. Это проверка переноса на другую структуру, а не множество независимых семейств. Целевой оборот постоянен. Отдельные разрезы могут содержать мало примеров.",
        "",
        "12 согласованных пользователем примеров пилота и делегированные правки — не независимая оценка модели. Датасет и рубрика не менялись. Результаты не подтверждают эффективность реального банковского AML.",
        "",
        "При провале критериев эта модель остаётся диагностическим артефактом. Следующий эксперимент требует отдельной версии и явной фиксации, что нынешний test уже просмотрен.",
    ]
    lines += [
        "",
        "## Покрытие и величина поведенческого эффекта",
        "",
        "Общие критерии не проверяют отсутствующие подгруппы. N=0 означает отсутствие проверки, а не нулевую ошибку.",
        "",
        "| Часть | Признак | Значение | N |",
        "|---|---|---|---:|",
    ]
    slices = pd.read_csv(output / "slices.csv")
    for row in slices[
        (slices.view == "clipped") & slices.dimension.isin(["salary", "cash"])
    ].itertuples():
        lines.append(f"| {row.split} | {row.dimension} | {row.value} | {row.n} |")
    lines += [
        "",
        "Совпадение направления парного изменения не означает совпадения его величины. Расхождения изменений более 5 баллов:",
        "",
    ]
    for row in pairs:
        if abs(row["predicted_delta"] - row["rubric_delta"]) > 5:
            lines.append(
                f"- {row['kind']}: модель {row['predicted_delta']:+.2f}, рубрика {row['rubric_delta']:+.2f} балла. Нужен отдельный разбор перед включением этого поведения в игру."
            )
    (output / "MODEL_CARD.md").write_text("\n".join(lines) + "\n")
