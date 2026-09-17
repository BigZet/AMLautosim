"""Exercise verifier gates with real files and a cheap scorer boundary."""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_model_integration as verifier


ROOT = Path(__file__).resolve().parents[2]


def inputs(tmp_path, count=4413, prediction="1", extra_prediction=False):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    rows = [dict(id=str(i), split="test", config_snapshot={}, steps=[]) for i in range(count)]
    (dataset / "scenarios.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    predictions = tmp_path / "predictions.csv"
    with predictions.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["id", "split", "prediction_raw"])
        writer.writerows((str(i), "test", prediction) for i in range(count))
        if extra_prediction:
            writer.writerow(["extra", "test", "1"])
    return dataset, predictions, tmp_path / "report.json"


def fake_scorer(raw=1.0, residual=0.0):
    return SimpleNamespace(
        identity={"version": "test"},
        score=lambda steps, config: {
            "explanation": {"raw_score": raw, "additivity_error": residual}
        },
    )


@pytest.mark.parametrize("mode", ["normal", "flag", "environment"])
@pytest.mark.parametrize("case", ["short", "empty", "prediction", "shap", "missing", "slow", "valid"])
def test_acceptance_gates_survive_optimization(tmp_path, mode, case):
    count = {"short": 1, "empty": 0}.get(case, 4413)
    dataset, predictions, output = inputs(
        tmp_path, count, prediction="2" if case == "prediction" else "1",
        extra_prediction=case == "missing",
    )
    # Run the real entry point and parsing; substitute only costly model inference
    # and, for the latency case, a deterministic one-second clock.
    program = """
import itertools, runpy, sys
from types import SimpleNamespace
from src.aml_workshop_simulator.services import model_scoring
model_scoring.get_model_scorer = lambda: SimpleNamespace(
    identity={'version': 'test'},
    score=lambda steps, config: {'explanation': {
        'raw_score': 1.0, 'additivity_error': RESIDUAL}})
if SLOW:
    import time
    time.perf_counter = lambda ticks=itertools.count(): float(next(ticks))
sys.argv = ['verify', '--dataset', DATASET, '--predictions', PREDICTIONS, '--output', OUTPUT]
runpy.run_module('scripts.verify_model_integration', run_name='__main__')
"""
    values = dict(RESIDUAL=0.001 if case == "shap" else 0, SLOW=case == "slow",
                  DATASET=str(dataset), PREDICTIONS=str(predictions), OUTPUT=str(output))
    program = "\n".join(f"{key} = {value!r}" for key, value in values.items()) + program
    env = os.environ.copy()
    env.pop("PYTHONOPTIMIZE", None)
    env["PYTHONUTF8"] = "1"
    if mode == "environment":
        env["PYTHONOPTIMIZE"] = "1"
    child = subprocess.run(
        [sys.executable, "-B", *(["-O"] if mode == "flag" else []), "-c", program],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    if case == "valid":
        assert child.returncode == 0, child.stderr
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["passed"] is True
        assert report["rows"] == 4413
        assert report["max_prediction_error"] == 0
        assert report["max_shap_additivity_error"] == 0
    else:
        assert child.returncode != 0, child.stdout
        assert "ValueError" in child.stderr, child.stderr
        assert not output.exists()


@pytest.mark.parametrize("field", ["prediction", "raw", "residual"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_measurements_never_pass(tmp_path, monkeypatch, field, value):
    paths = inputs(tmp_path, prediction=str(value) if field == "prediction" else "1")
    monkeypatch.setattr(verifier, "get_model_scorer", lambda: fake_scorer(
        raw=value if field == "raw" else 1.0,
        residual=value if field == "residual" else 0.0,
    ))
    with pytest.raises(ValueError, match="finite"):
        verifier.verify(*paths)
    assert not paths[2].exists()


@pytest.mark.parametrize("kind", ["duplicate_prediction", "duplicate_scenario", "unknown_scenario", "blank_prediction_id"])
def test_test_ids_are_complete_and_unique(tmp_path, monkeypatch, kind):
    dataset, predictions, output = inputs(tmp_path)
    if kind == "duplicate_prediction":
        with predictions.open("a", encoding="utf-8") as target:
            target.write("0,test,1\n")
    elif kind == "blank_prediction_id":
        text = predictions.read_text(encoding="utf-8")
        predictions.write_text(text.replace("0,test,1", ",test,1", 1), encoding="utf-8")
    else:
        source = dataset / "scenarios.jsonl"
        rows = source.read_text(encoding="utf-8").splitlines()
        if kind == "duplicate_scenario":
            rows.append(rows[0])
        else:
            row = json.loads(rows[0])
            row["id"] = "unknown"
            rows[0] = json.dumps(row)
        source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "get_model_scorer", fake_scorer)
    with pytest.raises(ValueError, match="[Ii][Dd]"):
        verifier.verify(dataset, predictions, output)
    assert not output.exists()


def test_output_created_during_verification_is_not_overwritten(tmp_path, monkeypatch):
    paths = inputs(tmp_path)
    scorer = fake_scorer()
    def load_scorer():
        paths[2].write_text("existing report", encoding="utf-8")
        return scorer
    monkeypatch.setattr(verifier, "get_model_scorer", load_scorer)
    with pytest.raises(FileExistsError):
        verifier.verify(*paths)
    assert paths[2].read_text(encoding="utf-8") == "existing report"
