import numpy as np
import pandas as pd
import pytest


def test_class_mapping_uses_positive_class_position_not_second_column():
    from scripts.aml_classifier import positive_probabilities

    class Reversed:
        classes_ = np.array([1, 0])

        def predict_proba(self, data):
            return np.array([[0.8, 0.2], [0.1, 0.9]])

    np.testing.assert_array_equal(
        positive_probabilities(Reversed(), object()), [0.8, 0.1]
    )
    model = Reversed()
    model.classes_ = np.array([0, 2])
    with pytest.raises(ValueError, match="classes"):
        positive_probabilities(model, object())


def test_feature_schema_forbids_implicit_column_reordering_or_extras():
    from scripts.aml_classifier import validated_features

    schema = {
        "features": ["amount", "kind"],
        "types": {"amount": "numeric", "kind": "categorical"},
    }
    frame = pd.DataFrame({"amount": [1.0, 2.0], "kind": ["a", "b"]})
    assert list(validated_features(frame, schema)) == ["amount", "kind"]
    for bad in (
        frame[["kind", "amount"]],
        frame.assign(label=[0, 1]),
        frame.drop(columns="kind"),
        frame.assign(amount=[np.nan, 2.0]),
    ):
        with pytest.raises(ValueError):
            validated_features(bad, schema)


def test_candidate_tie_breaking_uses_depth_trees_then_l2_without_test():
    from scripts.aml_classifier import select_candidate

    candidates = [
        {"depth": 8, "trees": 100, "l2_leaf_reg": 3, "validation_log_loss": 0.2000},
        {"depth": 4, "trees": 120, "l2_leaf_reg": 3, "validation_log_loss": 0.2010},
        {"depth": 4, "trees": 100, "l2_leaf_reg": 3, "validation_log_loss": 0.2015},
        {"depth": 4, "trees": 100, "l2_leaf_reg": 10, "validation_log_loss": 0.2019},
        {"depth": 4, "trees": 90, "l2_leaf_reg": 10, "validation_log_loss": 0.2030},
    ]
    assert select_candidate(candidates) == candidates[3]


def test_candidate_inclusive_tie_tolerance_is_stable_at_decimal_boundary():
    from scripts.aml_classifier import select_candidate

    candidates = [
        {"depth": 8, "trees": 100, "l2_leaf_reg": 3, "validation_log_loss": 0.200},
        {"depth": 4, "trees": 100, "l2_leaf_reg": 3, "validation_log_loss": 0.202},
    ]
    assert select_candidate(candidates) == candidates[1]


def test_seed_stability_checks_auc_and_both_confident_errors():
    from scripts.aml_classifier import seed_stability

    runs = [
        {"roc_auc": 0.96, "false_high": 0.01, "false_low": 0.02},
        {"roc_auc": 0.94, "false_high": 0.02, "false_low": 0.04},
        {"roc_auc": 0.95, "false_high": 0.03, "false_low": 0.02},
    ]
    assert seed_stability(runs)["passed"]
    runs[2]["false_low"] = 0.06
    assert not seed_stability(runs)["passed"]


def test_binary_catboost_save_load_preserves_positive_probability(tmp_path):
    from catboost import CatBoostClassifier, Pool
    from scripts.aml_classifier import positive_probabilities, validated_features

    frame = pd.DataFrame(
        {
            "amount": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "kind": ["a", "a", "b", "a", "b", "b"],
        }
    )
    schema = {
        "features": ["amount", "kind"],
        "types": {"amount": "numeric", "kind": "categorical"},
    }
    pool = Pool(
        validated_features(frame, schema),
        label=[0, 0, 0, 1, 1, 1],
        cat_features=["kind"],
    )
    model = CatBoostClassifier(
        iterations=8,
        depth=2,
        random_seed=2026091601,
        thread_count=4,
        verbose=False,
        allow_writing_files=False,
    )
    model.fit(pool)
    before = positive_probabilities(model, pool)
    model.save_model(str(tmp_path / "model.cbm"))
    loaded = CatBoostClassifier().load_model(str(tmp_path / "model.cbm"))
    np.testing.assert_allclose(
        positive_probabilities(loaded, pool), before, atol=1e-8, rtol=0
    )


def test_training_refuses_existing_output_before_reading_data(tmp_path):
    from scripts.aml_classifier import train

    with pytest.raises(FileExistsError):
        train(tmp_path / "missing", tmp_path / "missing.json", tmp_path)


def test_development_loader_never_parses_held_out_features(tmp_path):
    import json
    from scripts.aml_classifier import load_development

    schema = {
        "features": ["amount", "kind"],
        "types": {"amount": "numeric", "kind": "categorical"},
    }
    (tmp_path / "feature-schema.json").write_text(json.dumps(schema))
    (tmp_path / "split.csv").write_text(
        "scenario_id,group_id,split,aml_label\nt0,g0,train,0\nt1,g0,train,1\nv0,g1,validation,0\nv1,g1,validation,1\nx0,g2,test,0\n"
    )
    (tmp_path / "features.csv").write_text(
        "scenario_id,amount,kind\nt0,1,a\nt1,2,b\nv0,3,a\nv1,4,b\nx0,THIS MUST NEVER BE PARSED,\n"
    )
    actual_schema, development = load_development(tmp_path)
    assert actual_schema == schema
    assert set(development) == {"train", "validation"}
    assert development["train"]["ids"] == ["t0", "t1"]
    assert list(development["validation"]["features"]["amount"]) == [3.0, 4.0]
    (tmp_path / "split.csv").write_text(
        "scenario_id,group_id,split,aml_label\nt0,g0,train,0\nt1,g0,train,1\nv0,g0,validation,0\nv1,g0,validation,1\n"
    )
    with pytest.raises(ValueError, match="group"):
        load_development(tmp_path)


def test_training_rejects_not_release_ready_dataset(tmp_path, monkeypatch):
    from scripts import aml_classifier

    monkeypatch.setattr(
        aml_classifier, "audit_dataset", lambda path: {"release_ready": False}
    )
    with pytest.raises(ValueError, match="release-ready"):
        aml_classifier.train(
            tmp_path / "dataset", tmp_path / "protocol", tmp_path / "result"
        )
    assert not (tmp_path / "result").exists()


def test_training_requires_prefrozen_demo_before_loading_model_inputs(
    tmp_path, monkeypatch
):
    from scripts import aml_classifier

    monkeypatch.setattr(
        aml_classifier, "audit_dataset", lambda _: {"release_ready": True}
    )
    with pytest.raises(ValueError, match="frozen demo"):
        aml_classifier.train(
            tmp_path / "dataset", tmp_path / "protocol", tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()


def test_training_pipeline_freezes_grid_and_exports_only_development(
    tmp_path, monkeypatch
):
    import csv
    import json
    import catboost
    from scripts import aml_classifier

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    schema = {
        "features": ["amount", "kind"],
        "types": {"amount": "numeric", "kind": "categorical"},
    }
    (dataset / "feature-schema.json").write_text(json.dumps(schema))
    (dataset / "protocol.json").write_text("{}")
    (dataset / "manifest.json").write_text('{"fixture":true}')
    split_rows = ["scenario_id,group_id,split,aml_label"]
    feature_rows = ["scenario_id,amount,kind"]
    for split in ("train", "validation", "calibration-fit", "calibration-check"):
        for i in range(80 if split.startswith("calibration") else 20):
            sid = f"{split}-{i}"
            split_rows.append(f"{sid},{split}-g{i // 2},{split},{i % 2}")
            feature_rows.append(f"{sid},{i % 2},{'a' if i % 2 else 'b'}")
    split_rows.append("heldout,test-g,test,0")
    feature_rows.append("heldout,UNPARSED,")
    (dataset / "split.csv").write_text("\n".join(split_rows) + "\n")
    (dataset / "features.csv").write_text("\n".join(feature_rows) + "\n")
    monkeypatch.setattr(
        aml_classifier, "audit_dataset", lambda path: {"release_ready": True}
    )
    actual_class = catboost.CatBoostClassifier
    requested = []
    # Tiny model fixture isolates the separately tested real demo preflight.
    binding = {"scope": "unit-fixture-only", "independent": True}
    snapshot = {
        name: b"{}\n"
        for name in (
            "manifest.json",
            "casebook.json",
            "records.jsonl",
            "provenance.json",
            "protocol.json",
        )
    }
    monkeypatch.setattr(
        aml_classifier, "verify_frozen_demo", lambda *args: (binding, snapshot)
    )
    from sklearn.linear_model import LogisticRegression

    actual_logistic_fit = LogisticRegression.fit

    def check_prefit_binding(self, *args, **kwargs):
        assert json.loads((output / "demo-binding.json").read_bytes()) == binding
        assert all(
            (output / "demo-freeze" / name).read_bytes() == raw
            for name, raw in snapshot.items()
        )
        return actual_logistic_fit(self, *args, **kwargs)

    monkeypatch.setattr(LogisticRegression, "fit", check_prefit_binding)

    class TinyClassifier(actual_class):
        def __init__(self, **kwargs):
            if kwargs:
                requested.append(dict(kwargs))
                kwargs["iterations"] = (
                    8  # Unit fixture; production still requests3,000.
                )
            super().__init__(**kwargs)

    monkeypatch.setattr(catboost, "CatBoostClassifier", TinyClassifier)
    output = tmp_path / "model"
    aml_classifier.train(
        dataset,
        dataset / "protocol.json",
        output,
        frozen_demo=tmp_path / "unit-frozen-demo",
    )
    assert len(requested) == 8
    assert {(p["depth"], p["l2_leaf_reg"]) for p in requested[:6]} == {
        (d, l2) for d in (4, 6, 8) for l2 in (3, 10)
    }
    assert all(
        p["iterations"] == 3000
        and p["thread_count"] == 4
        and p["loss_function"] == "Logloss"
        for p in requested
    )
    assert [p["random_seed"] for p in requested[-2:]] == [2026091602, 2026091603]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["release_ready"] is False
    assert manifest["accessed_model_splits"] == ["train", "validation"]
    with (output / "development-predictions.csv").open() as handle:
        predictions = list(csv.DictReader(handle))
    assert len(predictions) == 40
    assert {r["split"] for r in predictions} == {"train", "validation"}
    assert (
        json.loads((output / "class-mapping.json").read_text())["positive_class"] == 1
    )
    assert aml_classifier.verify_training_artifact(output, dataset) == manifest
    binding["independent"] = False
    with pytest.raises(ValueError, match="demo binding"):
        aml_classifier.verify_training_artifact(output, dataset)
    binding["independent"] = True
    from scripts import calibrate_aml_classifier as calibration

    monkeypatch.setattr(
        calibration, "audit_dataset", lambda path: {"release_ready": True}
    )
    calibration_output = tmp_path / "calibration"
    calibration.calibrate(
        dataset, output, dataset / "protocol.json", calibration_output
    )
    calibration_manifest = json.loads(
        (calibration_output / "manifest.json").read_text()
    )
    assert calibration_manifest["release_ready"] is False
    assert calibration_manifest["status"] == "awaiting-independent-test"
    with (calibration_output / "calibration-predictions.csv").open() as handle:
        calibration_predictions = list(csv.DictReader(handle))
    assert len(calibration_predictions) == 160
    assert {r["split"] for r in calibration_predictions} == {
        "calibration-fit",
        "calibration-check",
    }
    assert (
        calibration_manifest["model_sha256"] == manifest["artifact_hashes"]["model.cbm"]
    )
    from scripts.package_aml_classifier import (
        _verify_calibration,
        _validate_calibration_predictions,
    )

    assert (
        _verify_calibration(
            calibration_output,
            manifest,
            {"fixture": True},
            dataset_path=dataset,
            model_path=output / "model.cbm",
        )
        == calibration_manifest
    )
    calibration_predictions[0]["group_id"] = "fabricated-independent-group"
    with (calibration_output / "calibration-predictions.csv").open(
        "w", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(calibration_predictions[0]))
        writer.writeheader()
        writer.writerows(calibration_predictions)
    with pytest.raises(ValueError, match="provenance"):
        _validate_calibration_predictions(
            calibration_output, dataset, output / "model.cbm"
        )
    (dataset / "protocol.json").write_text('{"different":true}')
    with pytest.raises(ValueError, match="another dataset/schema/protocol"):
        aml_classifier.verify_training_artifact(output, dataset)
    (dataset / "protocol.json").write_text("{}")
    model_path = output / "model.cbm"
    model_path.write_bytes(model_path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        aml_classifier.verify_training_artifact(output, dataset)
