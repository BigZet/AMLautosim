from copy import deepcopy
import json
import shutil

import pytest

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services import game_classifier as runtime


def test_registry_lists_only_current_package_without_client_paths():
    from src.aml_workshop_simulator.services.model_registry import (
        registry,
        classifier_paths,
    )

    value = registry()
    assert value["current_runtime"] == runtime.DEFAULT_PACKAGE.name
    assert {path.name for path in runtime.DEFAULT_PACKAGE.parent.iterdir() if path.is_dir()} == {
        runtime.DEFAULT_PACKAGE.name,
    }
    assert list(runtime.DEFAULT_PACKAGE.parent.rglob("*.cbm")) == [
        runtime.DEFAULT_PACKAGE / "model.cbm",
    ]
    assert {item["support"] for item in value["packages"]} == {
        "current",
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


def test_current_package_replays_release_baseline():
    current = runtime.get_game_classifier()
    baseline = json.loads((runtime.ROOT / 'tests/fixtures/retired_limits_baseline.json').read_bytes())
    for row in baseline['rows']:
        assert current.extract(row['steps']) == row['features']
        assert current.predict(row['steps'], current.context, require_pin=False, explain=False) == row['probability']


def test_unknown_pin_never_becomes_a_filesystem_path(monkeypatch):
    current = runtime.get_game_classifier()
    pin = {**current.identity, "package_sha256": "../../private"}
    with pytest.raises(Conflict, match="не найден"):
        runtime.get_pinned_game_classifier({**current.context, "risk_model": pin})


def test_resolver_only_uses_registered_locations(monkeypatch):
    from src.aml_workshop_simulator.services import model_registry

    old = runtime.get_game_classifier()
    monkeypatch.setattr(runtime, "get_game_classifier", lambda: type("Future", (), {"identity": {}, "release": {}})())
    monkeypatch.setattr(model_registry, "classifier_paths", lambda: ())
    with pytest.raises(Conflict, match="не найден"):
        runtime.get_pinned_game_classifier({**old.context, "risk_model": old.identity})


def test_registered_corrupt_model_fails_closed(tmp_path, monkeypatch):
    from src.aml_workshop_simulator.services import model_registry

    source = runtime.DEFAULT_PACKAGE
    old = runtime.GameClassifier(source)
    monkeypatch.setattr(runtime, "get_game_classifier", lambda: type("Future", (), {"identity": {}, "release": {}})())
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
