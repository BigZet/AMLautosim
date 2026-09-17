from copy import deepcopy
from types import SimpleNamespace
import pytest

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services import game_classifier as runtime


@pytest.mark.parametrize('name', ['aml-game-v1', 'aml-game-relaxed-v1', 'aml-game-attributes-v1', 'aml-game-attribute-context-v1'])
def test_saved_round_keeps_its_verified_package_after_default_changes(monkeypatch, name):
    previous = runtime.GameClassifier(runtime.ROOT / 'resources/catboost_models' / name)
    config = deepcopy(previous.context)
    config['risk_model'] = previous.identity
    future = SimpleNamespace(identity={'package_sha256':'future-default'})
    monkeypatch.setattr(runtime, 'get_game_classifier', lambda: future)
    selected = runtime.get_pinned_game_classifier(config)
    assert selected.identity == previous.identity
    selected.check_config(config, require_pin=True)
    config['risk_model'] = {**previous.identity, 'context_sha256':'tampered'}
    with pytest.raises(Conflict):
        runtime.get_pinned_game_classifier(config)


def test_unknown_pin_never_uses_current_default():
    with pytest.raises(Conflict, match='не найден'):
        runtime.get_pinned_game_classifier({'schema_version':10,'risk_model':{'package_sha256':'missing'}})
