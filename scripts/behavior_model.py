"""Behavior model v2: covered group validation, paired effects, untouched final holdout."""

import json
import shutil
import time
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from scripts.training_environment import collect_training_environment
from scripts.catboost_pipeline import (
    read,
    write,
    sha,
    frame_for_model,
    metrics,
    plots,
    slice_metrics,
)
from scripts.aml_dataset.expanded import label, valid, fingerprint
from scripts.aml_dataset.behavior_training import topology
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import (
    extract_features,
    FEATURE_VERSION,
)

BASES = ["absent", "payroll_registry", "service_contract", "no_reference"]
MODEL_VERSION = "aml-catboost-behavior-v2"


def load(directory):
    directory = Path(directory)
    checksums = read(directory / "CHECKSUMS.json")
    for name, expected in checksums.items():
        if Path(name).name != name or sha(directory / name) != expected:
            raise ValueError(f"Changed dataset file: {name}")
    manifest = read(directory / "manifest.json")
    schema = read(directory / "feature-schema.json")
    if manifest["extractor"] != FEATURE_VERSION or schema["version"] != FEATURE_VERSION:
        raise ValueError("Extractor mismatch")
    if manifest["rubric"] != "educational-risk-v2-final-1":
        raise ValueError("Unapproved rubric")
    frame = pd.read_csv(directory / "features.csv", keep_default_na=False)
    if list(frame) != schema["columns"] + ["target_risk_score"]:
        raise ValueError("Feature CSV schema mismatch")
    x = frame_for_model(frame, schema["columns"])
    y = frame.target_risk_score.to_numpy(dtype=float)
    split = pd.read_csv(directory / "split.csv", keep_default_na=False)
    if (
        len(x) != manifest["count"]
        or len(split) != len(x)
        or not np.array_equal(split.row_index, np.arange(len(x)))
    ):
        raise ValueError("Rows not aligned")
    if (
        not split.id.is_unique
        or not np.isfinite(y).all()
        or ((y < 0) | (y > 100)).any()
    ):
        raise ValueError("Invalid row/target")
    groups = {g["group"]: g for g in read(directory / "groups.json")}
    if any(groups[g]["split"] != s for g, s in zip(split.group, split.split)):
        raise ValueError("Group leakage")
    ids = {identity: i for i, identity in enumerate(split.id)}
    pairs = read(directory / "pairs.json")
    for pair in pairs:
        a, b = ids[pair["before"]], ids[pair["after"]]
        if (
            split.iloc[a].group != pair["group"]
            or split.iloc[b].group != pair["group"]
            or split.iloc[a].split != pair["split"]
            or split.iloc[b].split != pair["split"]
        ):
            raise ValueError("Pair leakage")
        pair["a"], pair["b"] = a, b
    return dict(
        path=directory,
        x=x,
        y=y,
        split=split,
        groups=groups,
        pairs=pairs,
        columns=schema["columns"],
        checksums=checksums,
        protocol=read(directory / "protocol.json"),
    )


def audit(data):
    rules = read(data["path"] / "rubric.json")
    if sha(data["path"] / "rubric.json") != sha(
        Path("config/synthetic_dataset/v2/rubric.json")
    ):
        # Same JSON can have different formatting; compare structure, never change weights.
        if rules != read("config/synthetic_dataset/v2/rubric.json"):
            raise ValueError("Rubric changed")
    seen = set()
    projected = {}
    rows = data["x"].to_dict("records")
    count = 0
    with (data["path"] / "scenarios.jsonl").open() as file:
        for i, line in enumerate(file):
            row = json.loads(line)
            part = data["split"].iloc[i]
            if (
                row["id"] != part.id
                or row["group"] != part.group
                or row["split"] != part.split
            ):
                raise ValueError("Raw alignment mismatch")
            if topology(row["steps"]) != data["groups"][part.group]["shape"]:
                raise ValueError("Descendant changed parent")
            if not valid(row["steps"], row["config_snapshot"]):
                raise ValueError("Invalid game scenario")
            computed = extract_features(row["steps"], row["config_snapshot"])
            for key, expected in rows[i].items():
                if isinstance(expected, str):
                    equal = computed[key] == expected
                else:
                    equal = np.isclose(computed[key], expected, rtol=0, atol=1e-8)
                if not equal:
                    raise ValueError(f"Feature mismatch {i} {key}")
            target, _ = label(computed, rules)
            if target != row["target_risk_score"] or abs(target - data["y"][i]) > 1e-8:
                raise ValueError("Label mismatch")
            observable = fingerprint(row["steps"], row["config_snapshot"])
            if observable != row["observable_hash"] or observable in seen:
                raise ValueError("Duplicate/incorrect observable fingerprint")
            seen.add(observable)
            key = tuple(rows[i].values())
            if key in projected and abs(projected[key] - target) > 1e-8:
                raise ValueError("Projected label conflict")
            projected[key] = target
            count += 1
            if count % 4000 == 0:
                print(f"AUDIT {count}/{len(rows)}", flush=True)
    if count != len(rows):
        raise ValueError("Raw row count mismatch")
    return dict(
        passed=True,
        rows=count,
        groups=len(data["groups"]),
        no_group_leakage=True,
        no_projected_label_conflicts=True,
        engine_and_extractor_verified=True,
    )


def weights(x):
    cells = (
        x.income_basis.astype(str)
        + "/"
        + (x.count_cash_withdrawal > 0).astype(int).astype(str)
    )
    counts = cells.value_counts()
    result = cells.map(lambda c: 1 / counts[c]).to_numpy(dtype=float)
    return result / result.mean()


def pair_errors(data, prediction, split):
    selected = [p for p in data["pairs"] if p["split"] == split]
    rows = []
    for pair in selected:
        a, b = pair["a"], pair["b"]
        expected = float(data["y"][b] - data["y"][a])
        actual = float(prediction[b] - prediction[a])
        rows.append(
            {k: pair[k] for k in ("group", "kind", "before", "after")}
            | dict(
                expected_delta=expected,
                predicted_delta=actual,
                delta_error=actual - expected,
            )
        )
    result = {}
    for kind in sorted({p["kind"] for p in rows}):
        part = [p for p in rows if p["kind"] == kind]
        error = np.array([abs(p["delta_error"]) for p in part])
        strong = [p for p in part if abs(p["expected_delta"]) > 3]
        result[kind] = dict(
            n=len(part),
            delta_mae=float(error.mean()),
            delta_p90=float(np.quantile(error, 0.9)),
            strong_n=len(strong),
            direction_rate=sum(
                p["expected_delta"] * p["predicted_delta"] > 0 for p in strong
            )
            / len(strong)
            if strong
            else None,
        )
    return result, rows


def assessment(data, prediction, split, baseline):
    mask = (data["split"].split == split).to_numpy()
    x = data["x"].loc[mask]
    y = data["y"][mask]
    pred = prediction[mask]
    raw = metrics(y, pred)
    clipped = np.clip(prediction, 0, 100)
    overall = metrics(y, clipped[mask])
    criteria = data["protocol"]["criteria"]
    income = {
        basis: metrics(
            y[(x.income_basis == basis).to_numpy()],
            clipped[mask][(x.income_basis == basis).to_numpy()],
        )
        for basis in BASES
    }
    cash = {
        str(value): metrics(
            y[((x.count_cash_withdrawal > 0) == value).to_numpy()],
            clipped[mask][((x.count_cash_withdrawal > 0) == value).to_numpy()],
        )
        for value in (False, True)
    }
    paired, _ = pair_errors(data, clipped, split)
    baseline_mae = float(np.abs(y - baseline).mean())
    checks = dict(
        overall_mae=overall["mae"] <= criteria["overall_mae_max"],
        beats_median=overall["mae"] < baseline_mae,
        high_coverage=overall["high_n"] > 0,
        high_under_rate=overall["high_n"] > 0
        and overall["high_under_15_rate"] <= criteria["high_under_rate_max"],
        high_below_50=overall["high_below_50_count"] == 0,
        income_coverage=all(
            m["n"] >= data["protocol"]["min_subgroup_rows"] for m in income.values()
        ),
        cash_coverage=all(
            m["n"] >= data["protocol"]["min_subgroup_rows"] for m in cash.values()
        ),
        income_accuracy=all(
            m["mae"] <= criteria["income_subgroup_mae_max"] for m in income.values()
        ),
        cash_accuracy=all(
            m["mae"] <= criteria["cash_subgroup_mae_max"] for m in cash.values()
        ),
        pair_accuracy=all(
            m["delta_mae"] <= criteria["pair_delta_mae_max"]
            and m["delta_p90"] <= criteria["pair_delta_p90_max"]
            for m in paired.values()
        ),
        pair_direction=all(
            m["direction_rate"] is None
            or m["direction_rate"] >= criteria["pair_strong_effect_direction_min"]
            for m in paired.values()
        ),
    )
    objective = float(
        np.mean(
            [
                overall["mae"],
                np.mean([m["mae"] for m in income.values()]),
                np.mean([m["delta_mae"] for m in paired.values()]),
            ]
        )
    )
    return dict(
        raw=raw,
        clipped=overall,
        income=income,
        cash=cash,
        pairs=paired,
        checks=checks,
        passed=all(checks.values()),
        objective=objective,
        median_baseline_mae=baseline_mae,
    )


def development_pairs(model, columns):
    result = []
    for line in (
        Path("resources/aml_dataset/review-v2-final-1/pairs.jsonl")
        .read_text()
        .splitlines()
    ):
        row = json.loads(line)
        x = pd.DataFrame(
            [
                extract_features(row[s]["steps"], row[s]["config_snapshot"])
                for s in ("before", "after")
            ]
        )
        predictions = np.clip(model.predict(frame_for_model(x, columns)), 0, 100)
        actual = float(predictions[1] - predictions[0])
        expected = (
            row["after"]["target_risk_score"] - row["before"]["target_risk_score"]
        )
        result.append(
            dict(
                kind=row["kind"],
                expected_delta=expected,
                predicted_delta=actual,
                delta_error=actual - expected,
            )
        )
    return result


def fit(data, params, columns, weighted=True):
    train = (data["split"].split == "train").to_numpy()
    validation = (data["split"].split == "validation").to_numpy()
    train_pool = Pool(
        data["x"].loc[train, columns],
        data["y"][train],
        cat_features=["income_basis"],
        weight=weights(data["x"].loc[train]) if weighted else None,
    )
    val_pool = Pool(
        data["x"].loc[validation, columns],
        data["y"][validation],
        cat_features=["income_basis"],
        weight=weights(data["x"].loc[validation]) if weighted else None,
    )
    model = CatBoostRegressor(**params)
    model.fit(
        train_pool,
        eval_set=val_pool,
        early_stopping_rounds=150,
        use_best_model=True,
        verbose=False,
    )
    return model


def validation_prediction(data, model, columns):
    # Explicitly never predict test during model selection.
    mask = (data["split"].split == "validation").to_numpy()
    prediction = np.full(len(data["x"]), np.nan)
    prediction[mask] = model.predict(data["x"].loc[mask, columns])
    return prediction


def train(directory, output):
    output = Path(output)
    if output.exists():
        raise ValueError("New experiment directory required")
    data = load(directory)
    inventory, environment = collect_training_environment()
    output.mkdir(parents=True)
    write(output / "protocol.json", data["protocol"])
    write(output / "input-checksums.json", data["checksums"])
    write(output / "audit.json", audit(data))
    shutil.copyfile(__file__, output / "training-source.py")
    (output / "environment.txt").write_text(inventory, encoding="utf-8")
    write(
        output / "environment.json",
        dict(
            **environment,
            source_sha256=sha(__file__),
        ),
    )
    base = float(np.median(data["y"][(data["split"].split == "train").to_numpy()]))
    config = data["protocol"]["training"]
    seed = data["protocol"]["model_seed"]
    old = [
        k
        for k in read("resources/catboost_models/experiment-v1/feature-schema.json")[
            "columns"
        ]
        if k in data["columns"]
    ]
    choices = [
        dict(
            name="ablation-old-unweighted",
            columns=old,
            weighted=False,
            depth=6,
            l2=3,
            loss="RMSE",
        ),
        dict(
            name="ablation-old-balanced",
            columns=old,
            weighted=True,
            depth=6,
            l2=3,
            loss="RMSE",
        ),
    ]
    choices += [
        dict(
            name=f"new-d{depth}-l2{l2}-{loss.split(':')[0]}",
            columns=data["columns"],
            weighted=True,
            depth=depth,
            l2=l2,
            loss=loss,
        )
        for depth, l2, loss in product(config["depths"], config["l2"], config["losses"])
    ]
    results = []
    (output / "candidates").mkdir()
    for choice in choices:
        params = dict(
            iterations=config["iterations"],
            learning_rate=config["learning_rate"],
            depth=choice["depth"],
            l2_leaf_reg=choice["l2"],
            loss_function=choice["loss"],
            eval_metric="MAE",
            random_seed=seed,
            thread_count=4,
            task_type="CPU",
            allow_writing_files=False,
        )
        start = time.monotonic()
        model = fit(data, params, choice["columns"], choice["weighted"])
        result = assessment(
            data,
            validation_prediction(data, model, choice["columns"]),
            "validation",
            base,
        )
        dev = development_pairs(model, choice["columns"])
        limits = {
            "salary": data["protocol"]["criteria"][
                "development_salary_delta_error_max"
            ],
            "party": data["protocol"]["criteria"]["development_party_delta_error_max"],
        }
        dev_pass = all(
            abs(row["delta_error"]) <= limits[row["kind"]]
            for row in dev
            if row["kind"] in limits
        )
        row = dict(
            id=choice["name"],
            columns=choice["columns"],
            weighted=choice["weighted"],
            params=params,
            trees=model.tree_count_,
            seconds=time.monotonic() - start,
            validation=result,
            development_pairs=dev,
            eligible=result["passed"] and dev_pass,
        )
        results.append(row)
        model.save_model(str(output / "candidates" / f"{choice['name']}.cbm"))
        write(
            output / "candidates" / f"{choice['name']}-history.json",
            model.get_evals_result(),
        )
        write(output / "experiments.json", results)
        print(
            f"{choice['name']}: MAE={result['clipped']['mae']:.3f} macro={result['objective']:.3f} trees={model.tree_count_} eligible={row['eligible']}; failed={[k for k, v in result['checks'].items() if not v]}; dev={[(r['kind'], round(r['delta_error'], 2)) for r in dev if r['kind'] in limits]}",
            flush=True,
        )
    eligible = [r for r in results if r["eligible"]]
    selected = min(
        eligible or results,
        key=lambda r: (r["validation"]["objective"], r["trees"], r["id"]),
    )
    write(
        output / "selection.json",
        dict(
            model_version=MODEL_VERSION,
            selected=selected,
            median_baseline=base,
            test_used=False,
            validation_ready=bool(eligible),
            seed=seed,
        ),
    )
    shutil.copyfile(
        output / "candidates" / f"{selected['id']}.cbm", output / "model.cbm"
    )
    write(
        output / "feature-schema.json",
        dict(
            version=FEATURE_VERSION,
            columns=selected["columns"],
            categorical=["income_basis"],
        ),
    )
    primary = CatBoostRegressor()
    primary.load_model(str(output / "model.cbm"))
    expected = validation_prediction(data, primary, selected["columns"])
    stability = []
    for other_seed in data["protocol"]["additional_seeds"]:
        other = fit(
            data,
            {**selected["params"], "random_seed": other_seed},
            selected["columns"],
            selected["weighted"],
        )
        result = assessment(
            data,
            validation_prediction(data, other, selected["columns"]),
            "validation",
            base,
        )
        stability.append(dict(seed=other_seed, validation=result))
        print("SEED", other_seed, result["objective"], result["passed"], flush=True)
    write(output / "stability.json", stability)
    repeated = fit(data, selected["params"], selected["columns"], selected["weighted"])
    mask = (data["split"].split == "validation").to_numpy()
    repeated_pred = validation_prediction(data, repeated, selected["columns"])[mask]
    repeat_delta = float(np.max(np.abs(repeated_pred - expected[mask])))
    repeated.save_model(str(output / "reproduced.cbm"))
    restored = CatBoostRegressor()
    restored.load_model(str(output / "reproduced.cbm"))
    reload_delta = float(
        np.max(
            np.abs(
                restored.predict(data["x"].loc[mask, selected["columns"]])
                - repeated_pred
            )
        )
    )
    permuted = frame_for_model(
        data["x"].loc[mask, list(reversed(selected["columns"]))], selected["columns"]
    )
    reorder_delta = float(np.max(np.abs(primary.predict(permuted) - expected[mask])))
    check = dict(
        repeat_delta=repeat_delta,
        reload_delta=reload_delta,
        reorder_delta=reorder_delta,
        passed=max(repeat_delta, reload_delta, reorder_delta) <= 1e-8,
    )
    write(output / "reproducibility.json", check)
    write(output / "model-checksum.json", dict(sha256=sha(output / "model.cbm")))
    if not check["passed"]:
        raise ValueError("Reproducibility failed")
    print(
        "TRAIN COMPLETE", selected["id"], "validation_ready", bool(eligible), flush=True
    )


def evaluate(directory, model_directory, output):
    output = Path(output)
    model_directory = Path(model_directory)
    if output.exists():
        raise ValueError("New report directory required")
    data = load(directory)
    selection = read(model_directory / "selection.json")
    columns = selection["selected"]["columns"]
    if read(model_directory / "input-checksums.json") != data["checksums"]:
        raise ValueError("Dataset changed")
    if selection["test_used"]:
        raise ValueError("Invalid selection protocol")
    if (
        sha(model_directory / "model.cbm")
        != read(model_directory / "model-checksum.json")["sha256"]
    ):
        raise ValueError("Model changed")
    model = CatBoostRegressor()
    model.load_model(str(model_directory / "model.cbm"))
    if model.feature_names_ != columns:
        raise ValueError("Schema mismatch")
    prediction = model.predict(frame_for_model(data["x"], columns))
    output.mkdir(parents=True)
    results = {
        s: assessment(data, prediction, s, selection["median_baseline"])
        for s in ("train", "validation", "test")
    }
    if (
        abs(
            results["validation"]["objective"]
            - selection["selected"]["validation"]["objective"]
        )
        > 1e-8
    ):
        raise ValueError("Selection predictions changed")
    ready = (
        selection["validation_ready"]
        and all(results[s]["passed"] for s in ("validation", "test"))
        and read(model_directory / "reproducibility.json")["passed"]
        and all(
            r["validation"]["passed"] for r in read(model_directory / "stability.json")
        )
    )
    write(
        output / "metrics.json",
        dict(
            ready_for_integration=ready,
            model_version=MODEL_VERSION,
            splits=results,
            fit_called=False,
        ),
    )
    frame = data["split"].copy()
    frame["target_risk_score"] = data["y"]
    frame["prediction_raw"] = prediction
    frame["prediction"] = np.clip(prediction, 0, 100)
    frame["error"] = frame.prediction - frame.target_risk_score
    frame.to_csv(output / "predictions.csv", index=False)
    slices = []
    pairs = []
    for s in ("train", "validation", "test"):
        mask = (data["split"].split == s).to_numpy()
        for view, p in [("raw", prediction), ("clipped", np.clip(prediction, 0, 100))]:
            slices.extend(
                dict(split=s, view=view, **r)
                for r in slice_metrics(data["x"].loc[mask], data["y"][mask], p[mask])
            )
        _, part = pair_errors(data, np.clip(prediction, 0, 100), s)
        pairs.extend(dict(split=s, **r) for r in part)
    pd.DataFrame(slices).to_csv(output / "slices.csv", index=False)
    pd.DataFrame(pairs).to_csv(output / "pairs.csv", index=False)
    importance = pd.DataFrame(
        dict(
            feature=columns,
            importance=model.get_feature_importance(
                type="PredictionValuesChange", thread_count=4
            ),
        )
    ).sort_values("importance", ascending=False)
    importance.to_csv(output / "feature-importance.csv", index=False)
    test = frame[frame.split == "test"]
    indices = set(test.nsmallest(20, "error").index) | set(
        test.nlargest(20, "error").index
    )
    errors = []
    with (data["path"] / "scenarios.jsonl").open() as file:
        for i, line in enumerate(file):
            if i in indices:
                errors.append(
                    dict(
                        **json.loads(line),
                        prediction=float(frame.iloc[i].prediction),
                        error=float(frame.iloc[i].error),
                    )
                )
    write(output / "largest-errors.json", errors)
    mask = (data["split"].split == "test").to_numpy()
    plots(output, data["y"][mask], np.clip(prediction[mask], 0, 100), importance)
    write(output / "development-pairs.json", development_pairs(model, columns))
    write(
        output / "evaluation-code.json",
        dict(sha256=sha(__file__), model_sha256=sha(model_directory / "model.cbm")),
    )
    report(output, model_directory, results, ready)
    write(
        output / "CHECKSUMS.json",
        {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
    print(
        "FINAL EVALUATION",
        ready,
        "test MAE",
        results["test"]["clipped"]["mae"],
        "failed",
        [k for k, v in results["test"]["checks"].items() if not v],
        flush=True,
    )
    return ready


def report(output, model_directory, results, ready):
    selection = read(model_directory / "selection.json")
    lines = [
        "# Итоговая модель поведения v2",
        "",
        f"Готовность к интеграции по протоколу: **{ready}**. В API игры не подключена.",
        "",
        f"Модель {selection['selected']['id']}, деревьев {selection['selected']['trees']}. Рубрика educational-risk-v2-final-1 не менялась.",
        "",
        "| Часть | N | MAE | RMSE | P90 | Высокий риск | Сильное занижение | Высокий риск ниже 50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s, r in results.items():
        m = r["clipped"]
        lines.append(
            f"| {s} | {m['n']} | {m['mae']:.3f} | {m['rmse']:.3f} | {m['p90_abs_error']:.3f} | {m['high_n']} | {m['high_under_15_count']} | {m['high_below_50_count']} |"
        )
    lines += [
        "",
        "## Проверка зарплаты и наличных",
        "",
        "| Часть | Подгруппа | N | MAE |",
        "|---|---|---:|---:|",
    ]
    for s in ("validation", "test"):
        for kind in ("income", "cash"):
            for value, m in results[s][kind].items():
                lines.append(f"| {s} | {kind}: {value} | {m['n']} | {m['mae']:.3f} |")
    lines += [
        "",
        "## Парные эффекты на новых test-группах",
        "",
        "| Изменение | N пар | MAE изменения | P90 ошибки изменения | Доля верных направлений для эффекта >3 |",
        "|---|---:|---:|---:|---:|",
    ]
    for kind, m in results["test"]["pairs"].items():
        lines.append(
            f"| {kind} | {m['n']} | {m['delta_mae']:.3f} | {m['delta_p90']:.3f} | {m['direction_rate']} |"
        )
    lines += [
        "",
        "## Известные диагностические пары",
        "",
        "Не независимый test: использовались при разработке и выборе на validation.",
        "",
        "| Эффект | Рубрика | Модель | Ошибка изменения |",
        "|---|---:|---:|---:|",
    ]
    for r in read(output / "development-pairs.json"):
        lines.append(
            f"| {r['kind']} | {r['expected_delta']:.3f} | {r['predicted_delta']:.3f} | {r['delta_error']:.3f} |"
        )
    lines += [
        "",
        "![Ошибки](test-errors.png)",
        "",
        "![Признаки](feature-importance.png)",
        "",
        "## Протокол и ограничения",
        "",
        "Разделение по независимо построенным C/D-структурам: варианты суммы, сторон, зарплаты, покупок, наличных и времени внутри одной структуры не пересекают части. Проверочные структуры отличаются от ранее просмотренных v1; старый test теперь только материал разработки. Новая проверка всё равно синтетическая, а не внешняя банковская валидация.",
        "",
        "Сравнены прежние признаки без весов, прежние признаки с балансировкой и расширенные наблюдаемые агрегаты. Ни одна фича не содержит рубрику или целевую оценку. Подбор и остановка используют только validation; test открыт после selection.json. Дополнительные seed не заменяют основную модель.",
        "",
        "Все основные цепочки достигают цели и проходят игровой движок. Разрезы, ошибки с объяснениями и пары доступны в CSV/JSON рядом. Низкие риски, недопустимые цепочки, незавершённые сценарии и изменённый баланс игры не являются подтверждённой областью применения. Риск — учебная оценка, не вероятность обнаружения банком.",
    ]
    (output / "MODEL_CARD.md").write_text("\n".join(lines) + "\n")
