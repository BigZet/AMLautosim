from decimal import Decimal
from collections import Counter

from scripts.aml_game_curriculum_v5 import candidate, catalog
from scripts.aml_game_curriculum import catalog as original_catalog
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from src.aml_workshop_simulator.core.game_config import base_game_config, load_config


def test_new_defaults_preserve_history_and_resource_budgets():
    config, _ = catalog()
    old, _ = original_catalog()
    assert config['objectives'] == load_config('game_curriculum_defaults_v1.json')['objectives']
    assert base_game_config()['objectives']['target_outflow'] == '400000.00'
    assert config['objectives'] == dict(target_outflow='360000.00',max_actions=14)
    assert config['resources'] == old['resources']
    assert config['behavior'] == old['behavior']
    assert old['objectives']['target_outflow'] == '400000.00'


def test_broad_amounts_stay_in_card_bounds_and_support_two_funding_routes():
    funding = Counter()
    totals = set()
    for seed in range(2030800000,2030800240):
        config, steps, _, _ = candidate(seed)
        bounds = {c['code']:(Decimal(c['min_amount']),Decimal(c['max_amount'])) for c in config['card_snapshots']}
        total = Decimal(0)
        for step in steps:
            low, high = bounds[step['card']['code']]
            assert low <= Decimal(step['amount']) <= high
            if step['card']['code'] in ('card_transfer','cash_withdrawal'):
                total += Decimal(step['amount'])
        assert total in (360000,380000,400000)
        totals.add(total)
        if not submit_blockers(evaluate(steps,config)):
            codes = Counter(s['card']['code'] for s in steps)
            funding[(codes['incoming_transfer'],codes['salary'])] += 1
    assert len(totals) == 3
    assert funding[(2,1)] > 0
    assert funding[(3,0)] > 0
