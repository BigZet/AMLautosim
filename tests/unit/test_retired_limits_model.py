import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services.game_classifier import get_game_classifier, get_pinned_game_classifier, game_config


def test_retired_limits_preserve_predictions_and_active_pin():
    baseline = json.loads((Path(__file__).parents[1] / 'fixtures/retired_limits_baseline.json').read_text())
    model = get_game_classifier()
    config = {**model.context, 'risk_model': baseline['identity']}
    assert get_pinned_game_classifier(config) is model
    model.check_config(config, require_pin=True)
    for row in baseline['rows']:
        assert model.extract(row['steps']) == row['features']
        assert model.predict(row['steps'], config, explain=False) == row['probability']
    changed = deepcopy(config)
    changed['leaderboard']['weights'] = {'stealth': '0.50', 'resources': '0.50'}
    with pytest.raises(Conflict):
        model.check_config(changed, require_pin=True)
    clean = game_config()['constraints']
    assert 'max_night_operations' not in clean
    assert 'max_anonymous_operations' not in clean
    assert 'anonymous' not in clean['category_limits']
