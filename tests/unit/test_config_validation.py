"""Configuration errors must fail before serving requests or writing seed data."""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import seed_database
from src.aml_workshop_simulator.api.main import app, lifespan
from src.aml_workshop_simulator.schemas import catalog_config


def test_invalid_files_stop_startup_and_seed(invalid_game_config, monkeypatch):
    config, message = invalid_game_config
    monkeypatch.setattr(catalog_config, "base_game_config", lambda: config)
    session_factory = Mock(side_effect=AssertionError("Seed opened the database"))
    monkeypatch.setattr(seed_database, "AsyncSessionLocal", session_factory)

    with pytest.raises(ValueError, match=message):
        catalog_config.validate_configuration_files()

    async def start():
        async with lifespan(app):
            pytest.fail("Invalid configuration reached application startup")

    with pytest.raises(ValueError, match=message):
        asyncio.run(start())
    with pytest.raises(ValueError, match=message):
        asyncio.run(seed_database.seed())
    session_factory.assert_not_called()


def test_cli_validates_selected_directory(invalid_game_config, tmp_path):
    config, message = invalid_game_config
    root = Path(__file__).resolve().parents[2]
    directory = tmp_path / "config"
    shutil.copytree(root / "config", directory)
    (directory / "base_round.json").write_text(json.dumps(config), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.validate_config",
            "--config-dir",
            str(directory),
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert message in result.stderr
