"""Training provenance must describe this process without requiring pip or fitting."""

import importlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from types import SimpleNamespace

import pytest


class StopAfterProvenance(Exception):
    pass


@pytest.fixture(params=["scripts.behavior_model", "scripts.catboost_pipeline"])
def training_prefix(request, monkeypatch):
    module = importlib.import_module(request.param)
    behavior = request.param.endswith("behavior_model")
    data = dict(protocol={}, checksums={}, columns=["income_basis"])
    monkeypatch.setattr(module, "load" if behavior else "load_dataset", lambda _: data)
    monkeypatch.setattr(
        module,
        "audit" if behavior else "verify_raw_features",
        lambda _: {"passed": True},
    )
    original_write = module.write

    def write_and_stop(path, value):
        original_write(path, value)
        if Path(path).name == "environment.json":
            raise StopAfterProvenance

    def forbid_training(*args, **kwargs):
        pytest.fail("Provenance tests must never fit or construct a model")

    monkeypatch.setattr(module, "write", write_and_stop)
    monkeypatch.setattr(module, "fit" if behavior else "fit_one", forbid_training)
    monkeypatch.setattr(module, "CatBoostRegressor", forbid_training)
    monkeypatch.setattr(module, "Pool", forbid_training)
    return module


@pytest.mark.parametrize("path_kind", ["missing", "hostile"])
def test_training_records_active_environment_without_path_python_or_pip(
    training_prefix, tmp_path, monkeypatch, path_kind
):
    # A return to PATH-selected pip freeze must fail even when it would exit zero.
    monkeypatch.setenv("PATH", "" if path_kind == "missing" else str(tmp_path))

    def wrong_python(*args, **kwargs):
        if path_kind == "missing":
            raise FileNotFoundError("No PATH python or pip")
        return "foreign-package==0.0\n"

    monkeypatch.setattr(subprocess, "check_output", wrong_python)
    output = tmp_path / "experiment"
    with pytest.raises(StopAfterProvenance):
        training_prefix.train("unused dataset", output)
    saved = json.loads((output / "environment.json").read_text(encoding="utf-8"))
    assert saved["executable"] == sys.executable
    assert saved["prefix"] == sys.prefix
    assert saved["python"] == platform.python_version()
    assert saved["platform"] == platform.platform()
    assert saved["packages"] == {
        name: metadata.version(name) for name in ("catboost", "numpy", "pandas")
    }
    requirements = (output / "environment.txt").read_text(encoding="utf-8").splitlines()
    for name in ("catboost", "numpy", "pandas"):
        assert f"{name}=={metadata.version(name)}" in requirements
    assert requirements == sorted(set(requirements))
    assert "foreign-package==0.0" not in requirements
    if training_prefix.__name__.endswith("behavior_model"):
        assert saved["source_sha256"] == training_prefix.sha(training_prefix.__file__)
    else:
        assert saved["pipeline"] == training_prefix.VERSION
        assert saved["pipeline_sha256"] == training_prefix.sha(training_prefix.__file__)


@pytest.mark.parametrize(
    "inventory", [[], [SimpleNamespace(metadata={"Name": "numpy"}, version="2.0")]]
)
def test_missing_ml_metadata_does_not_reserve_experiment_directory(
    training_prefix, tmp_path, monkeypatch, inventory
):
    monkeypatch.setattr(metadata, "distributions", lambda: iter(inventory))
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "")
    output = tmp_path / "nested" / "experiment"
    with pytest.raises(ValueError, match="[Mm]issing.*catboost"):
        training_prefix.train("unused dataset", output)
    assert not output.parent.exists()


def test_inventory_is_normalized_deduplicated_and_sorted(
    training_prefix, tmp_path, monkeypatch
):
    inventory = [
        ("Z_Package", "2.0"),
        ("pandas", "3.0"),
        ("NumPy", "2.0"),
        ("CatBoost", "1.2"),
        ("z-package", "2.0"),
    ]
    monkeypatch.setattr(
        metadata,
        "distributions",
        lambda: (
            SimpleNamespace(metadata={"Name": name}, version=version)
            for name, version in inventory
        ),
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "")
    output = tmp_path / "experiment"
    with pytest.raises(StopAfterProvenance):
        training_prefix.train("unused dataset", output)
    assert (output / "environment.txt").read_text(encoding="utf-8") == (
        "catboost==1.2\nnumpy==2.0\npandas==3.0\nz-package==2.0\n"
    )


@pytest.mark.parametrize("extra", [("NumPy", "1.0"), (None, "1.0"), ("other", "")])
def test_ambiguous_or_invalid_inventory_fails_before_directory_creation(
    training_prefix, tmp_path, monkeypatch, extra
):
    inventory = [("catboost", "1.2"), ("numpy", "2.0"), ("pandas", "3.0"), extra]
    monkeypatch.setattr(
        metadata,
        "distributions",
        lambda: (
            SimpleNamespace(metadata={"Name": name}, version=version)
            for name, version in inventory
        ),
    )
    output = tmp_path / "experiment"
    with pytest.raises(ValueError, match="distribution metadata"):
        training_prefix.train("unused dataset", output)
    assert not output.exists()
