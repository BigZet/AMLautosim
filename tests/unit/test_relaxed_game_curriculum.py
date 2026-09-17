from collections import defaultdict
from decimal import Decimal

from scripts.aml_game_curriculum_v7 import candidate as before_amounts
from scripts.aml_game_curriculum_v8 import candidate, catalog
from scripts.aml_game_curriculum_v5 import catalog as original_catalog
from src.aml_workshop_simulator.domain.operation_purposes import validate_purpose


def gross(steps):
    result = defaultdict(Decimal)
    for step in steps:
        kind = step['card']['code']
        direction = 'inflow' if kind in ('incoming_transfer','salary') else 'outflow' if kind in ('card_transfer','cash_withdrawal') else kind
        result[direction] += Decimal(step['amount'])
    return result


def test_relaxation_preserves_history_and_conserves_funding():
    config, _ = catalog()
    original, _ = original_catalog()
    assert config['behavior'] == original['behavior']
    assert config['resources']['initial_balance'] == original['resources']['initial_balance']
    assert config['objectives']['target_outflow'] == original['objectives']['target_outflow']
    for seed in range(2031900000, 2031900200):
        _, old, *_ = before_amounts(seed)
        actual, steps, *_ = candidate(seed)
        assert actual == config
        assert gross(steps) == gross(old)
        assert len({s['step_id'] for s in steps}) == len(steps)
        for step in steps:
            validate_purpose(step)
            assert Decimal(step['amount']) > 0
