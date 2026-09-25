"""Contextual model: API persistence, explanations and fixed settings on PostgreSQL."""
import json
from pathlib import Path
import pytest

from tests.api import test_game_classifier_release as historical


@pytest.fixture
def seeded_game_version():
    return 10


@pytest.fixture(autouse=True)
def contextual_package(monkeypatch):
    monkeypatch.setenv('AML_PROBABILITY_MODEL_PATH',str(Path(__file__).parents[2]/'resources/catboost_models/aml-game-attribute-context-v1'))


def test_contextual_examples_end_to_end(request_api,admin,round_id,player_factory,command,sql,monkeypatch):
    examples=json.loads((Path(__file__).parents[1]/'fixtures/attribute_context_examples.json').read_bytes())
    monkeypatch.setattr(historical,'EXAMPLES',examples)
    historical.test_published_examples_end_to_end(request_api,admin,round_id,player_factory,command,sql)


def test_contextual_history_and_settings_frozen(request_api,admin,round_id,monkeypatch,tmp_path):
    historical.test_fixed_context_limits_and_package_failure(request_api,admin,round_id,monkeypatch,tmp_path)

pytestmark = pytest.mark.usefixtures("scoring_worker")
