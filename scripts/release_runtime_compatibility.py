"""Rebind an explicit package only after replaying preserved numerical evidence.

Run as a module from the repository root. Only release.json is replaced, after
all checks; weights, datasets, manifests and acceptance evidence are untouched.
"""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile

from src.aml_workshop_simulator.services import game_classifier as runtime
from src.aml_workshop_simulator.services.source_hashing import source_sha256


def _write(path: Path, value: dict) -> None:
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def refresh(package: Path, baseline_path: Path) -> dict:
    package = package.resolve()
    original_bytes = (package / 'release.json').read_bytes()
    original = json.loads(original_bytes)
    baseline = json.loads(baseline_path.read_bytes())
    if len(baseline['rows']) < 25:
        raise ValueError('At least 25 preserved replay chains are required')
    for name, expected in original['files'].items():
        if runtime.file_hash(package / name) != expected:
            raise ValueError('Artifact drift: ' + name)

    release = deepcopy(original)
    release['source_hash_mode'] = 'lf-v1'
    release.setdefault('compatibility_sources', {})[
        'src/aml_workshop_simulator/services/source_hashing.py'
    ] = None
    release['compatibility_sources'][
        'src/aml_workshop_simulator/domain/russian_plural.py'
    ] = None
    changed = {}
    for section in ('inference_sources', 'compatibility_sources'):
        for name in release[section]:
            actual = source_sha256(runtime.ROOT / name)
            before = original.get(section, {}).get(name)
            if actual != before:
                changed[name] = {'before': before, 'after': actual}
            release[section][name] = actual

    with tempfile.TemporaryDirectory(prefix='aml-source-release-') as directory:
        staged = Path(directory) / 'package'
        shutil.copytree(package, staged)
        _write(staged / 'release.json', release)
        model = runtime.GameClassifier(staged)
        previous_sha = runtime.digest(original)
        previous_identity = dict(model.identity, package_sha256=previous_sha,
                                 model_version='aml-game:sha256:' + previous_sha)
        prior_pins = [previous_identity, *original.get('compatible_identities', [])]
        if baseline['identity'] not in prior_pins:
            raise ValueError('Baseline is not bound to the previous package identity')
        for index, row in enumerate(baseline['rows']):
            prediction = model.predict(row['steps'], baseline['config'], require_pin=False)
            prediction.pop('model_identity')
            if prediction != row['prediction']:
                raise ValueError(f'Replay mismatch for chain {index}; refusing compatibility')

        needs_refresh = bool(changed) or original.get('source_hash_mode') != 'lf-v1'
        pins = prior_pins if needs_refresh else original.get('compatible_identities', [])
        unique = {runtime.digest(pin): pin for pin in pins}
        release['compatible_identities'] = list(unique.values())
        if needs_refresh:
            release['source_compatibility'] = {
                'baseline_sha256': runtime.file_hash(baseline_path),
                'compared_chains': len(baseline['rows']),
                'features_probabilities_shap_equal': True,
            }
        _write(staged / 'release.json', release)
        model = runtime.GameClassifier(staged)
        model.check_config(baseline['config'], require_pin=True)
        result = {'previous_identity': previous_identity, 'identity': model.identity,
                  'changed_sources': changed, 'replayed_chains': len(baseline['rows'])}
        if original != release:
            if (package / 'release.json').read_bytes() != original_bytes:
                raise ValueError('Release changed concurrently; retry from a new baseline')
            with tempfile.NamedTemporaryFile(dir=package, prefix='.release-', delete=False) as stream:
                temporary = Path(stream.name)
            try:
                temporary.write_bytes((staged / 'release.json').read_bytes())
                os.replace(temporary, package / 'release.json')
            finally:
                temporary.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('baseline', type=Path)
    args = parser.parse_args()
    print(json.dumps(refresh(args.package, args.baseline), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
