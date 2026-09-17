"""Exercise new limits through persistence, scoring and result presentation."""
import json
from pathlib import Path

import pytest

from tests.api import test_game_classifier_release as historical


@pytest.fixture(autouse=True)
def relaxed_package(monkeypatch):
    monkeypatch.setenv('AML_PROBABILITY_MODEL_PATH', str(Path(__file__).parents[2] / 'resources/catboost_models/aml-game-relaxed-v1'))


@pytest.fixture
def seeded_game_version():
    return 10


def test_relaxed_examples_end_to_end(
    request_api, admin, round_id, player_factory, command, sql, monkeypatch
):
    config = request_api("GET", "/admin/rounds/current", admin)["game_config"]
    assert config["resources"]["initial_energy"] == 34
    assert config["resources"]["initial_time"] == 34
    assert config["objectives"]["max_actions"] == 16
    examples = json.loads(
        (Path(__file__).parents[1] / "fixtures/relaxed_classifier_examples.json").read_text(encoding="utf8")
    )
    monkeypatch.setattr(historical, "EXAMPLES", examples)
    historical.test_published_examples_end_to_end(
        request_api, admin, round_id, player_factory, command, sql
    )


def test_relaxed_context_is_frozen(request_api, admin, round_id, monkeypatch, tmp_path):
    historical.test_fixed_context_limits_and_package_failure(
        request_api, admin, round_id, monkeypatch, tmp_path
    )
