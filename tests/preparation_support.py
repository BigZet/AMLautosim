"""Deterministic input matrix frozen before canonical preparation optimization."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

from scripts.check_expanded_balance import demo_config, demo_steps
from tests.aml_context_support import context_fixture
from src.aml_workshop_simulator.core.errors import ApplicationError
from src.aml_workshop_simulator.services.scenario_service import prepare_scenario, payload_hash


def cases():
    for version in (8, 10):
        config, source = (demo_config(), demo_steps(demo_config())) if version == 8 else context_fixture()
        for count in (0, 1, 9, 16):
            steps = [deepcopy(source[i % len(source)]) for i in range(count)]
            for i, step in enumerate(steps):
                step['step_id'] = str(UUID(int=i+1))
                step['interval_minutes'] = None if i == 0 else 1
            yield f'v{version}-{count}', deepcopy(config), steps
        for variant in ('duplicate', 'unknown_field', 'unknown_party', 'negative_amount', 'overrides'):
            value, steps = deepcopy(config), deepcopy(source)
            if variant == 'duplicate':
                steps[1]['step_id'] = steps[0]['step_id']
            elif variant == 'unknown_field':
                steps[0]['action_details']['unknown_field'] = 'unexpected'
            elif variant == 'unknown_party':
                steps[0]['sender_id'] = 'missing'
            elif variant == 'negative_amount':
                steps[0]['amount'] = '-1'
            else:
                value['resources']['initial_balance'] = '50000.00'
            yield f'v{version}-{variant}', value, steps


def outcome(config, steps):
    try:
        canonical, snapshot = prepare_scenario(SimpleNamespace(game_config=config), steps)
        return {'steps': canonical, 'snapshot': snapshot, 'payload_hash': payload_hash(canonical)}
    except ApplicationError as exc:
        return {'error': type(exc).__name__, 'code': exc.code, 'message': exc.message, 'details': exc.details}
    except ValueError as exc:
        return {'error': type(exc).__name__, 'message': str(exc)}
