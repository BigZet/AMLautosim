"""Relaxed monetary and resource limits with explicit coverage mutations.

Fixed history and total funding/outflow are preserved. No model predictions are
used to choose mutations. Full financial simulation decides feasibility.
"""
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
import random

from scripts.aml_game_curriculum_v7 import candidate as previous_candidate, catalog as previous_catalog
from src.aml_workshop_simulator.core.game_config import load_config


@lru_cache(maxsize=1)
def catalog():
    old, templates = previous_catalog()
    config = deepcopy(old)
    defaults = load_config('game_curriculum_defaults_v4.json')
    config['resources'] = deepcopy(defaults['resources'])
    config['objectives'] = deepcopy(defaults['objectives'])
    config['constraints'].update(deepcopy(defaults['constraints']))
    for operation in config['operations']:
        operation.update(defaults['operation_overrides'].get(operation['code'], {}))
    assert config['behavior'] == old['behavior']
    return config, templates


def concentrate(steps, code, rng):
    selected = [s for s in steps if s['card']['code'] == code]
    if len(selected) < 2:
        return
    left, right = rng.sample(selected, 2)
    total = Decimal(left['amount']) + Decimal(right['amount'])
    target = min(Decimal(rng.randint(81000,100000)), total - 10000)
    if target > 80000:
        left['amount'], right['amount'] = str(target), str(total-target)


def candidate(seed):
    _, steps, family, topology = previous_candidate(seed)
    config, _ = catalog()
    rng = random.Random(seed ^ 0x982CAF)
    # One quarter remains a route/amount control; others explore the expanded limits.
    if seed % 4:
        if rng.random() < .6:
            concentrate(steps, 'incoming_transfer', rng)
        if rng.random() < .6:
            concentrate(steps, 'card_transfer', rng)
        cash = [s for s in steps if s['card']['code'] == 'cash_withdrawal']
        cards = [s for s in steps if s['card']['code'] == 'card_transfer']
        if cash and cards and rng.random() < .65:
            target = rng.choice(cash)
            donor = rng.choice(cards)
            total_cash = sum(Decimal(s['amount']) for s in cash)
            delta = min(Decimal(rng.randint(15000,45000)), Decimal('150000')-total_cash,
                        Decimal('120000')-Decimal(target['amount']), Decimal(donor['amount'])-10000)
            if delta > 0:
                target['amount'] = str(Decimal(target['amount'])+delta)
                donor['amount'] = str(Decimal(donor['amount'])-delta)
        # Coalesce only adjacent payments to the same recipient, preserving direction.
        if rng.random() < .2:
            for i in range(len(steps)-1):
                a,b = steps[i:i+2]
                if (a['card']['code'] == b['card']['code'] == 'card_transfer'
                    and a.get('recipient_id') == b.get('recipient_id')
                    and Decimal(a['amount'])+Decimal(b['amount']) <= 100000):
                    a['amount'] = str(Decimal(a['amount'])+Decimal(b['amount']))
                    del steps[i+1]
                    break
    return config, steps, family, topology
