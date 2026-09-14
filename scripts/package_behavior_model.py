"""Package and verify an approved model without wiring it into the live game."""

import argparse
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.catboost_pipeline import read, write, sha
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import FEATURE_VERSION
from src.aml_workshop_simulator.services.aml_risk_model import (
    AMLRiskModel,
    contract_signature,
)


def renamed_context(steps, config):
    steps, config = deepcopy(steps), deepcopy(config)
    mapping = {
        p["id"]: f"opaque-{i}"
        for i, p in enumerate(config["behavior"]["counterparties"])
    }
    for p in config["behavior"]["counterparties"]:
        p["id"] = mapping[p["id"]]
    for row in steps:
        for key in ("sender_id", "recipient_id"):
            if row.get(key) is not None:
                row[key] = mapping[row[key]]
    for event in config["behavior"]["history"]["operations"] or []:
        event["counterparty_id"] = mapping[event["counterparty_id"]]
    return steps, config


def package(dataset, experiment, evaluation, output):
    dataset, experiment, evaluation, output = map(
        Path, (dataset, experiment, evaluation, output)
    )
    if output.exists():
        raise ValueError("Package output must be new")
    if not read(evaluation / "metrics.json")["ready_for_integration"]:
        raise ValueError("Quality gates not passed")
    if (
        not read(experiment / "audit.json")["passed"]
        or not read(experiment / "reproducibility.json")["passed"]
    ):
        raise ValueError("Verification incomplete")
    if any(not s["validation"]["passed"] for s in read(experiment / "stability.json")):
        raise ValueError("Seed instability")
    expected_inputs = read(experiment / "input-checksums.json")
    for name, digest in expected_inputs.items():
        if sha(dataset / name) != digest:
            raise ValueError("Changed input dataset")
    output.mkdir(parents=True)
    for name in ("model.cbm", "feature-schema.json"):
        shutil.copyfile(experiment / name, output / name)
    manifest = dict(
        model_version="aml-catboost-behavior-v2",
        extractor=FEATURE_VERSION,
        ready_for_integration=True,
        integrated_into_game=False,
        game_contract_signature=contract_signature(read(dataset / "base-config.json")),
        checksums={
            name: sha(output / name) for name in ("model.cbm", "feature-schema.json")
        },
        dataset_checksums=expected_inputs,
        source_checksums={
            name: sha(Path("src/aml_workshop_simulator/services") / name)
            for name in (
                "aml_risk_model.py",
                "aml_dataset_features_v3.py",
                "aml_dataset_features_v2.py",
                "aml_episodes.py",
            )
        },
        quality_report=str(evaluation / "metrics.json"),
        inference_validation="pending",
    )
    write(output / "manifest.json", manifest)
    try:
        model = AMLRiskModel(output)
        predictions = pd.read_csv(evaluation / "predictions.csv").set_index("id")
        latencies = []
        max_error = 0
        renamed_checked = 0
        count = 0
        first = None
        with (dataset / "scenarios.jsonl").open() as file:
            for line in file:
                row = json.loads(line)
                if row["split"] != "test":
                    continue
                if first is None:
                    first = row
                start = time.perf_counter()
                value = model.predict(row["steps"], row["config_snapshot"])
                latencies.append((time.perf_counter() - start) * 1000)
                max_error = max(
                    max_error,
                    abs(value - float(predictions.loc[row["id"], "prediction"])),
                )
                if renamed_checked < 12:
                    steps, config = renamed_context(
                        row["steps"], row["config_snapshot"]
                    )
                    if abs(model.predict(steps, config) - value) > 1e-8:
                        raise ValueError("Raw IDs changed prediction")
                    renamed_checked += 1
                count += 1
        if count != int((predictions["split"] == "test").sum()) or max_error > 1e-8:
            raise ValueError("Packaged inference differs from held-out evaluation")
        features = first["features"]
        expected = model.predict_features(features)
        reordered = dict(reversed(list(features.items())))
        if abs(model.predict_features(reordered) - expected) > 1e-8:
            raise ValueError("Feature order changes inference")
        missing = dict(features)
        missing.pop(model.columns[0])
        rejections = {}
        for kind, operation in [
            ("missing_feature", lambda: model.predict_features(missing)),
            (
                "nonfinite",
                lambda: model.predict_features(
                    {**features, model.columns[0]: float("inf")}
                ),
            ),
            ("invalid_chain", lambda: model.predict([], first["config_snapshot"])),
            (
                "legacy_v7",
                lambda: model.predict(
                    first["steps"], {**first["config_snapshot"], "schema_version": 7}
                ),
            ),
            (
                "changed_balance",
                lambda: model.predict(
                    first["steps"],
                    {
                        **first["config_snapshot"],
                        "resources": {
                            **first["config_snapshot"]["resources"],
                            "initial_balance": "999999",
                        },
                    },
                ),
            ),
        ]:
            try:
                operation()
            except ValueError:
                rejections[kind] = True
            else:
                raise ValueError(f"Unrejected invalid input: {kind}")
        # A modified binary must be rejected before CatBoost loading.
        original = (output / "model.cbm").read_bytes()
        try:
            (output / "model.cbm").write_bytes(original + b"changed")
            try:
                AMLRiskModel(output)
            except ValueError:
                rejections["changed_model"] = True
            else:
                raise ValueError("Modified model accepted")
        finally:
            (output / "model.cbm").write_bytes(original)
        p95 = float(np.quantile(latencies, 0.95))
        report = dict(
            passed=True,
            test_rows=count,
            max_prediction_difference=max_error,
            renamed_id_checks=renamed_checked,
            invalid_inputs_rejected=rejections,
            latency_ms=dict(
                median=float(np.median(latencies)), p95=p95, max=max(latencies)
            ),
            model_sha256=sha(output / "model.cbm"),
        )
        if p95 > 100:
            raise ValueError(f"Inference latency exceeds 100ms p95: {p95}")
        write(output / "inference-verification.json", report)
        manifest["inference_validation"] = "passed"
        write(output / "manifest.json", manifest)
        shutil.copyfile(evaluation / "MODEL_CARD.md", output / "MODEL_CARD.md")
        # Keep relative chart/report links in the copied card valid.
        for name in (
            "test-errors.png",
            "feature-importance.png",
            "metrics.json",
            "slices.csv",
            "pairs.csv",
            "development-pairs.json",
        ):
            shutil.copyfile(evaluation / name, output / name)
        (output / "README.md").write_text(
            """# Модель для отдельного этапа интеграции\n\nМодель прошла новый протокол качества и проверку полного пути inference на всех\ntest-цепочках. В приложение ещё не подключена.\n\nИспользование: `AMLRiskModel(path).predict(steps, config)` из\n`src.aml_workshop_simulator.services.aml_risk_model`. Результат — float 0–100.\nМодель загружается один раз при создании экземпляра; приложение само её не включает.\n\nПоддерживаются допустимые завершённые сценарии v8 с проверенным финансовым\nконтрактом. Изменённые ресурсы/лимиты и v7 отклоняются; им нужен прежний скорер\nили отдельно проверенная модель. Профиль, история и ID сторон не зашиты в бинарник.\n\n[Паспорт](MODEL_CARD.md), [метрики](metrics.json),\n[проверка inference](inference-verification.json), [manifest](manifest.json).\n\nРиск отражает синтетическую учебную рубрику; это не банковская вероятность.\n"""
        )
        write(
            output / "CHECKSUMS.json",
            {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        )
        print("PACKAGE VERIFIED", report, flush=True)
    except Exception:
        manifest["ready_for_integration"] = False
        manifest["inference_validation"] = "failed"
        write(output / "manifest.json", manifest)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    for arg in ("dataset", "experiment", "evaluation", "output"):
        parser.add_argument("--" + arg, required=True)
    a = parser.parse_args()
    package(a.dataset, a.experiment, a.evaluation, a.output)
