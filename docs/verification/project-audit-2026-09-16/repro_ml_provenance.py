"""Read-only production audit: exercise train provenance, never train a model.

Run from repository root with PYTHONUTF8=1:
  .venv/Scripts/python.exe docs/verification/project-audit-2026-09-16/repro_ml_provenance.py
Only this directory's JSON evidence is persisted; train outputs use temporary dirs.
"""

import hashlib
import importlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PACKAGES = ("catboost", "numpy", "pandas")
SOURCES = ("scripts/behavior_model.py", "scripts/catboost_pipeline.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process(executable, arguments):
    result = subprocess.run(
        [executable, *arguments], text=True, capture_output=True, timeout=30
    )
    return dict(
        requested_executable=executable,
        arguments=arguments,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def freeze_summary(text):
    return dict(
        line_count=len(text.splitlines()),
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        ml_dependencies=[
            line for line in text.splitlines()
            if line.lower().startswith(tuple(f"{name}==" for name in PACKAGES))
        ],
    )


class StopAfterProvenance(Exception):
    pass


def train_prefix(module_name, scenario):
    module = importlib.import_module(module_name)
    is_behavior = module_name.endswith("behavior_model")
    load_name = "load" if is_behavior else "load_dataset"
    audit_name = "audit" if is_behavior else "verify_raw_features"
    fit_name = "fit" if is_behavior else "fit_one"
    data = dict(protocol={}, checksums={}, columns=["income_basis"])
    original_write = module.write

    def write_and_stop(path, value):
        original_write(path, value)
        if Path(path).name == "environment.json":
            raise StopAfterProvenance("Stopped before any training")

    with tempfile.TemporaryDirectory(prefix="aml-provenance-audit-") as temporary:
        output = Path(temporary) / "experiment"
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, load_name, return_value=data))
            stack.enter_context(patch.object(module, audit_name, return_value={"passed": True}))
            stack.enter_context(patch.object(module, "write", side_effect=write_and_stop))
            fit = stack.enter_context(patch.object(module, fit_name, side_effect=AssertionError("Training forbidden")))
            ctor = stack.enter_context(patch.object(module, "CatBoostRegressor", side_effect=AssertionError("Model construction forbidden")))
            if scenario == "missing_python":
                stack.enter_context(patch.object(module.subprocess, "check_output", side_effect=FileNotFoundError("Injected missing python executable")))
            elif scenario == "missing_pip":
                stack.enter_context(patch.object(module.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, ["python", "-m", "pip", "freeze"], stderr="Injected missing pip")))
            try:
                module.train("mock dataset, not read", output)
            except (StopAfterProvenance, FileNotFoundError, subprocess.CalledProcessError) as exc:
                outcome = dict(exception=type(exc).__name__, message=str(exc))
            else:
                raise AssertionError("Training unexpectedly continued")
            outcome.update(
                module=module_name,
                scenario=scenario,
                files_left=sorted(p.name for p in output.iterdir()),
                fit_calls=fit.call_count,
                model_constructor_calls=ctor.call_count,
            )
            if (output / "environment.txt").exists():
                outcome["saved_freeze"] = freeze_summary((output / "environment.txt").read_text())
            if (output / "environment.json").exists():
                outcome["saved_environment"] = json.loads((output / "environment.json").read_text())
            try:
                module.train("mock dataset, not read", output)
            except ValueError as exc:
                outcome["retry_exception"] = type(exc).__name__
                outcome["retry_message"] = str(exc)
            else:
                raise AssertionError("Expected existing-directory guard")
            assert fit.call_count == ctor.call_count == 0
            assert (output / "model.cbm").exists() is False
            return outcome


def main():
    before = {name: digest(ROOT / name) for name in SOURCES}
    child_code = "import sys,platform,json; print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,version=platform.python_version())))"
    result = dict(
        scope="Provenance only; actual train prefix with mocked loading/audit; no fitting",
        parent=dict(executable=sys.executable, base_executable=getattr(sys, "_base_executable", None), prefix=sys.prefix, python=platform.python_version()),
        path_python=shutil.which("python"),
        active_dependencies={name: importlib.metadata.version(name) for name in PACKAGES},
        child_interpreters=[process(exe, ["-c", child_code]) for exe in dict.fromkeys(("python", sys.executable, shutil.which("python"))) if exe],
    )
    freezes = []
    for exe in ("python", sys.executable):
        freeze = process(exe, ["-m", "pip", "freeze"])
        freeze["summary"] = freeze_summary(freeze.pop("stdout"))
        freezes.append(freeze)
    result["freeze_probes"] = freezes
    result["train_probes"] = [
        train_prefix(module, scenario)
        for module in ("scripts.behavior_model", "scripts.catboost_pipeline")
        for scenario in ("actual_freeze", "missing_python", "missing_pip")
    ]
    result["archived_environments"] = [
        dict(path=str(path.relative_to(ROOT)), environment=json.loads(path.read_text()), freeze=freeze_summary((path.parent / "environment.txt").read_text()))
        for path in sorted((ROOT / "resources/catboost_models").rglob("environment.json"))
    ]
    result["sources_before"] = before
    result["sources_after"] = {name: digest(ROOT / name) for name in SOURCES}
    assert result["sources_before"] == result["sources_after"]
    target = Path(__file__).with_name("ml-provenance.json")
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(evidence=str(target), probes=len(result["train_probes"]), production_unchanged=True, real_training_calls=0), indent=2))


if __name__ == "__main__":
    main()
