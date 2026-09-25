"""Submission and scoring through the updated package in a disposable database."""
from pathlib import Path
import pytest

from tests.api import test_game_classifier_release as historical


@pytest.fixture
def seeded_game_version():
    return 10


@pytest.fixture(autouse=True)
def current_package(monkeypatch):
    monkeypatch.setenv('AML_PROBABILITY_MODEL_PATH', str(Path(__file__).parents[2] / 'resources/catboost_models/aml-game-organizer-settings-v1'))


def test_submission_and_scoring(request_api, admin, round_id, player_factory, command, sql, monkeypatch):
    import json
    examples = json.loads((Path(__file__).parents[1] / 'fixtures/attribute_classifier_examples.json').read_text(encoding='utf-8'))
    baseline = json.loads((Path(__file__).parents[1] / 'fixtures/retired_limits_baseline.json').read_text())
    for example, before in zip(examples, baseline['rows'], strict=True):
        assert example['steps'] == before['steps']
        example['probability'] = before['probability']
    monkeypatch.setattr(historical, 'EXAMPLES', examples)
    historical.test_published_examples_end_to_end(request_api, admin, round_id, player_factory, command, sql)

pytestmark = pytest.mark.usefixtures("scoring_worker")
