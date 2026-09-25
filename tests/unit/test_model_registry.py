from copy import deepcopy
import json
import shutil

import pytest

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services import game_classifier as runtime


def test_registry_lists_current_legacy_research_without_client_paths():
    from src.aml_workshop_simulator.services.model_registry import (
        registry,
        classifier_paths,
    )

    value = registry()
    assert value["current_runtime"] == runtime.DEFAULT_PACKAGE.name
    assert {item["support"] for item in value["packages"]} == {
        "current",
        "legacy",
        "research",
    }
    assert all(
        path.parent == runtime.DEFAULT_PACKAGE.parent for path in classifier_paths()
    )
    assert "aml-game-attribute-context-unlimited-v1" not in {
        p.name for p in classifier_paths()
    }


def test_every_current_compatible_pin_resolves_without_retired_package():
    current = runtime.get_game_classifier()
    for pin in [current.identity, *current.release["compatible_identities"]]:
        config = {**deepcopy(current.context), "risk_model": pin}
        assert runtime.get_pinned_game_classifier(config) is current
        current.check_config(config, require_pin=True)


def test_all_unlimited_package_pins_replay_through_current_runtime():
    current = runtime.get_game_classifier()
    retired = runtime.DEFAULT_PACKAGE.parent / 'aml-game-attribute-context-unlimited-v1'
    release = json.loads((retired / 'release.json').read_bytes())
    hashes = {runtime.digest(release), *(p['package_sha256'] for p in release['compatible_identities'])}
    pins = [p for p in current.release['compatible_identities'] if p['package_sha256'] in hashes]
    assert {p['package_sha256'] for p in pins} == hashes
    baseline = json.loads((runtime.ROOT / 'tests/fixtures/retired_limits_baseline.json').read_bytes())
    for pin in pins:
        config = {**deepcopy(current.context), 'risk_model': pin}
        assert runtime.get_pinned_game_classifier(config) is current
        for row in baseline['rows']:
            assert current.extract(row['steps']) == row['features']
            assert current.predict(row['steps'], config, explain=False) == row['probability']


@pytest.mark.parametrize(
    "name",
    [
        "aml-game-v1",
        "aml-game-relaxed-v1",
        "aml-game-attributes-v1",
        "aml-game-attribute-context-v1",
    ],
)
def test_registered_historical_pin_resolves(name):
    model = runtime.GameClassifier(runtime.DEFAULT_PACKAGE.parent / name)
    config = {**deepcopy(model.context), "risk_model": model.identity}
    resolved = runtime.get_pinned_game_classifier(config)
    assert resolved.identity == model.identity
    resolved.check_config(config, require_pin=True)


def test_unknown_pin_never_becomes_a_filesystem_path(monkeypatch):
    current = runtime.get_game_classifier()
    pin = {**current.identity, "package_sha256": "../../private"}
    with pytest.raises(Conflict, match="не найден"):
        runtime.get_pinned_game_classifier({**current.context, "risk_model": pin})


def test_resolver_only_uses_registered_locations(monkeypatch):
    from src.aml_workshop_simulator.services import model_registry

    old = runtime.GameClassifier(runtime.DEFAULT_PACKAGE.parent / "aml-game-v1")
    monkeypatch.setattr(model_registry, "classifier_paths", lambda: ())
    with pytest.raises(Conflict, match="не найден"):
        runtime.get_pinned_game_classifier({**old.context, "risk_model": old.identity})


def test_registered_corrupt_historical_model_fails_closed(tmp_path, monkeypatch):
    from src.aml_workshop_simulator.services import model_registry

    source = runtime.DEFAULT_PACKAGE.parent / "aml-game-v1"
    old = runtime.GameClassifier(source)
    destination = tmp_path / source.name
    shutil.copytree(source, destination)
    with (destination / "model.cbm").open("ab") as stream:
        stream.write(b"corrupt")
    monkeypatch.setattr(model_registry, "classifier_paths", lambda: (destination,))
    with pytest.raises(Conflict) as error:
        runtime.get_pinned_game_classifier({**old.context, "risk_model": old.identity})
    assert error.value.code == "model_unavailable"


def test_registry_rejects_escaped_server_path(tmp_path, monkeypatch):
    from src.aml_workshop_simulator.services import model_registry

    value = deepcopy(model_registry.registry())
    value["packages"][0]["path"] = "../outside"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(model_registry, "REGISTRY_PATH", path)
    with pytest.raises(ValueError, match="path"):
        model_registry.registry()
