"""Release verification must fail closed, including optimized Python."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from src.aml_workshop_simulator.services.game_classifier import GameClassifier

ROOT = Path(__file__).resolve().parents[2]


def snapshot(path):
    return {
        str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize(
    "script,source_name",
    [
        ("package_organizer_settings", "aml-game-organizer-settings-v1"),
    ],
)
def test_verified_publication_and_failed_refresh(
    tmp_path, optimized, script, source_name
):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "resources/catboost_models" / source_name, source)
    model = GameClassifier(source)
    baseline = json.loads(
        (ROOT / "tests/fixtures/retired_limits_baseline.json").read_text()
    )
    baseline["identity"] = model.identity
    baseline_file = tmp_path / "baseline.json"
    output = tmp_path / "output"
    command = [
        sys.executable,
        *(["-O"] if optimized else []),
        "-m",
        "scripts." + script,
        str(source),
        str(baseline_file),
        str(output),
    ]

    def run():
        baseline_file.write_text(json.dumps(baseline))
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

    result = run()
    assert result.returncode == 0, result.stderr
    assert "Verified 25" in result.stdout
    if script == "package_organizer_settings":
        result = run()
        assert result.returncode == 0, result.stderr
    saved = snapshot(output)
    baseline["rows"][0]["probability"] = 0.54321
    result = run()
    assert result.returncode != 0 and "Verified" not in result.stdout
    assert snapshot(output) == saved
    # Bad inputs must also leave a new destination absent.
    output = tmp_path / "rejected"
    command[-1] = str(output)
    result = run()
    assert result.returncode != 0 and not output.exists()
    baseline["rows"][0]["probability"] = model.predict(
        baseline["rows"][0]["steps"], model.context, require_pin=False, explain=False
    )
    baseline["identity"]["package_sha256"] = "tampered"
    result = run()
    assert result.returncode != 0 and not output.exists()
    baseline["identity"] = model.identity
    with (source / "features.json").open("a") as file:
        file.write(" ")
    result = run()
    assert result.returncode != 0 and not output.exists()
