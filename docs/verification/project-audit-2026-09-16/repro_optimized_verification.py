"""Exercise real integration verification on one real test row, without training.

Run from the repository root with .venv/Scripts/python.exe and PYTHONUTF8=1.
All child reports live in an automatically removed temporary directory.
The normal full verification report is never opened or written.
"""

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AUDIT = Path(__file__).resolve().parent
SOURCE = ROOT / "scripts/verify_model_integration.py"
DATASET = ROOT / "resources/aml_dataset/behavior-v3/release"
PREDICTIONS = ROOT / "resources/catboost_models/experiment-v2/evaluation/predictions.csv"
PACKAGE = ROOT / "resources/catboost_models/integration-v2-final"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = digest(SOURCE)
    with PREDICTIONS.open(encoding="utf-8", newline="") as source:
        expected_count = sum(row["split"] == "test" for row in csv.DictReader(source))
    selected = None
    with (DATASET / "scenarios.jsonl").open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            if row["split"] == "test":
                selected = (row["id"], line)
                break
    if selected is None:
        raise RuntimeError("No real test row found")
    environment = os.environ.copy()
    environment.pop("PYTHONOPTIMIZE", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["AML_MODEL_PATH"] = str(PACKAGE)
    modes = (("normal", [], None), ("flag_O", ["-O"], None), ("env_optimize_1", [], "1"))
    probes = []
    with tempfile.TemporaryDirectory(prefix="optimized-verification-", dir=AUDIT) as temporary:
        mini = Path(temporary) / "one-real-test-row"
        mini.mkdir()
        (mini / "scenarios.jsonl").write_text(selected[1], encoding="utf-8")
        for mode, flags, optimize in modes:
            output = Path(temporary) / f"{mode}-result.json"
            child_env = environment.copy()
            if optimize is not None:
                child_env["PYTHONOPTIMIZE"] = optimize
            command = [
                sys.executable, "-B", *flags, "-m", "scripts.verify_model_integration",
                "--dataset", str(mini), "--predictions", str(PREDICTIONS),
                "--output", str(output),
            ]
            child = subprocess.run(
                command, cwd=ROOT, env=child_env, text=True,
                capture_output=True, timeout=90,
            )
            report = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
            probes.append(dict(
                mode=mode, python_flags=["-B", *flags], PYTHONOPTIMIZE=optimize,
                returncode=child.returncode, output_created=output.exists(),
                stdout=child.stdout, stderr=child.stderr, report=report,
            ))
            print(json.dumps(dict(mode=mode, returncode=child.returncode, report=report)), flush=True)
    result = dict(
        finding="Conditional P3: assert quality gates disappear under optimized Python",
        verifier=str(SOURCE.relative_to(ROOT)), verifier_sha256_before=before,
        verifier_sha256_after=digest(SOURCE),
        python_executable=sys.executable, python_version=sys.version.split()[0],
        dataset=str(DATASET.relative_to(ROOT)), copied_real_test_rows=1,
        selected_test_id=selected[0], copied_line_sha256=hashlib.sha256(selected[1].encode()).hexdigest(),
        predictions=str(PREDICTIONS.relative_to(ROOT)), predictions_sha256=digest(PREDICTIONS),
        real_predictions_test_rows=expected_count, real_scorer=True,
        model_package=str(PACKAGE.relative_to(ROOT)),
        model_manifest_sha256=digest(PACKAGE / "manifest.json"),
        probes=probes,
        main_model_integration_report_touched=False,
    )
    normal, *optimized = probes
    confirmed = (
        normal["returncode"] != 0 and "AssertionError" in normal["stderr"]
        and not normal["output_created"] and expected_count == 4413
        and all(p["returncode"] == 0 and p["report"]["passed"] is True
                and p["report"]["rows"] == 1 for p in optimized)
        and before == result["verifier_sha256_after"]
    )
    result["confirmed"] = confirmed
    target = AUDIT / "optimized-verification.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(confirmed=confirmed, evidence=str(target))), flush=True)
    if not confirmed:
        raise RuntimeError("Observed results differ from the proposed reproduction")


if __name__ == "__main__":
    main()
