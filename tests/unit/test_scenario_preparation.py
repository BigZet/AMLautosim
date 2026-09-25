import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.preparation_support import cases, outcome
from src.aml_workshop_simulator.services.scenario_service import prepare_scenario

BASELINE = {row['name']: row['expected'] for row in json.loads((Path(__file__).parents[1]/'fixtures/scenario_preparation_baseline.json').read_bytes())}


@pytest.mark.parametrize('name,config,steps', list(cases()), ids=lambda value: value if isinstance(value,str) else None)
def test_preparation_matches_frozen_outputs_and_preserves_inputs(name, config, steps):
    original = deepcopy((config, steps))
    assert outcome(config, steps) == BASELINE[name]
    assert (config, steps) == original


@pytest.mark.parametrize('version', [8, 10])
def test_prepare_canonicalizes_each_contract_once(monkeypatch, version):
    from src.aml_workshop_simulator.services import aml_context, counterparties, expanded_simulation
    module = aml_context if version == 10 else counterparties
    name = 'canonical_steps' if version == 10 else 'canonical_expanded_steps'
    original = getattr(module, name)
    calls = []
    def counted(steps, config):
        calls.append(config['schema_version'])
        return original(steps, config)
    monkeypatch.setattr(module, name, counted)
    if version == 8:
        monkeypatch.setattr(expanded_simulation, name, counted)
    _, config, steps = next(c for c in cases() if c[0] == f'v{version}-9')
    prepare_scenario(SimpleNamespace(game_config=config), steps)
    assert calls == [version]
