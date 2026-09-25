"""Source EOL is portable; changes to code or any artifact still fail closed."""

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from src.aml_workshop_simulator.services import game_classifier as runtime


def test_source_hash_is_independent_of_eol_but_not_code(tmp_path):
    from src.aml_workshop_simulator.services.source_hashing import source_sha256

    source = tmp_path / 'source.py'
    expected = sha256(b'value = 1\n').hexdigest()
    for data in (b'value = 1\n', b'value = 1\r\n'):
        source.write_bytes(data)
        assert source_sha256(source) == expected
    source.write_bytes(b'value = 2\r\n')
    assert source_sha256(source) != expected


def test_artifact_hash_preserves_every_byte(tmp_path):
    artifact = tmp_path / 'model.cbm'
    artifact.write_bytes(b'CBM\x00\r\n')
    original = runtime.file_hash(artifact)
    artifact.write_bytes(b'CBM\x00\n')
    assert runtime.file_hash(artifact) != original


def staged_sources(tmp_path, monkeypatch, mode):
    package = tmp_path / 'package'
    shutil.copytree(runtime.DEFAULT_PACKAGE, package)
    release = json.loads((package / 'release.json').read_bytes())
    root = tmp_path / 'root'
    for section in ('inference_sources', 'compatibility_sources'):
        for name in release.get(section, {}):
            source = root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            data = (runtime.ROOT / name).read_bytes().replace(b'\r\n', b'\n')
            source.write_bytes(data)
            release[section][name] = sha256(data).hexdigest()
    if mode is None:
        release.pop('source_hash_mode', None)
    else:
        release['source_hash_mode'] = mode
    (package / 'release.json').write_text(json.dumps(release), encoding='utf-8')
    monkeypatch.setattr(runtime, 'ROOT', root)
    return package, root, release


@pytest.mark.parametrize('eol', [b'\n', b'\r\n'])
def test_lf_release_loads_both_checkouts_and_rejects_changed_source(tmp_path, monkeypatch, eol):
    package, root, release = staged_sources(tmp_path, monkeypatch, 'lf-v1')
    for section in ('inference_sources', 'compatibility_sources'):
        for name in release.get(section, {}):
            source = root / name
            source.write_bytes(source.read_bytes().replace(b'\n', eol))
    model = runtime.GameClassifier(package)
    source = root / next(iter(release['inference_sources']))
    source.write_bytes(source.read_bytes() + b'\nchanged = True\n')
    with pytest.raises(ValueError, match='implementation changed'):
        model.verify_integrity()


@pytest.mark.parametrize('mode', [None, 'raw-v1'])
def test_legacy_source_mode_stays_byte_exact(tmp_path, monkeypatch, mode):
    package, root, release = staged_sources(tmp_path, monkeypatch, mode)
    model = runtime.GameClassifier(package)
    source = root / next(iter(release['inference_sources']))
    source.write_bytes(source.read_bytes().replace(b'\n', b'\r\n'))
    with pytest.raises(ValueError, match='implementation changed'):
        model.verify_integrity()


def test_unknown_source_mode_is_rejected(tmp_path, monkeypatch):
    package, _, _ = staged_sources(tmp_path, monkeypatch, 'future-v99')
    with pytest.raises(ValueError, match='source hash mode'):
        runtime.GameClassifier(package)


def test_source_mode_does_not_allow_artifact_eol_changes(tmp_path, monkeypatch):
    package, _, _ = staged_sources(tmp_path, monkeypatch, 'lf-v1')
    model = runtime.GameClassifier(package)
    artifact = package / 'context.json'
    artifact.write_bytes(artifact.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='artifact changed'):
        model.verify_integrity()


def test_release_replays_original_predictions_and_preserves_old_pin():
    baseline = json.loads((Path(__file__).parents[1] / 'fixtures/runtime_compatibility_baseline.json').read_bytes())
    model = runtime.get_game_classifier()
    for row in baseline['rows']:
        prediction = model.predict(row['steps'], baseline['config'])
        prediction.pop('model_identity')
        assert prediction == row['prediction']
    assert baseline['identity'] in model.release['compatible_identities']
    identities = model.release['compatible_identities']
    assert len(identities) == len({runtime.digest(identity) for identity in identities})


def test_failed_compatibility_replay_never_publishes(tmp_path):
    from scripts.release_runtime_compatibility import refresh

    package = tmp_path / 'package'
    shutil.copytree(runtime.DEFAULT_PACKAGE, package)
    before = (package / 'release.json').read_bytes()
    baseline = json.loads((Path(__file__).parents[1] / 'fixtures/runtime_compatibility_baseline.json').read_bytes())
    baseline['rows'][0]['prediction']['aml_probability'] += 0.01
    evidence = tmp_path / 'bad-baseline.json'
    evidence.write_text(json.dumps(baseline), encoding='utf-8')
    with pytest.raises(ValueError, match='Replay mismatch'):
        refresh(package, evidence)
    assert (package / 'release.json').read_bytes() == before


def test_compatibility_refresh_is_idempotent_and_does_not_change_artifacts(tmp_path):
    from scripts.release_runtime_compatibility import refresh

    package = tmp_path / 'package'
    shutil.copytree(runtime.DEFAULT_PACKAGE, package)
    evidence = Path(__file__).parents[1] / 'fixtures/runtime_compatibility_baseline.json'
    before = {name: runtime.file_hash(package / name) for name in runtime.REQUIRED}
    first = refresh(package, evidence)
    release = (package / 'release.json').read_bytes()
    second = refresh(package, evidence)
    assert second['identity'] == first['identity']
    assert (package / 'release.json').read_bytes() == release
    assert before == {name: runtime.file_hash(package / name) for name in runtime.REQUIRED}
