"""First measured relaxation: wider action/resource budgets, same fixed history.

Mutations conserve gross flow and are sampled before labels or model predictions.
The full game engine remains the authority on whether a chain is playable.
"""
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
import random
from uuid import NAMESPACE_URL, uuid5

from scripts.aml_game_curriculum_v5 import candidate as previous_candidate, catalog as previous_catalog
from src.aml_workshop_simulator.core.game_config import load_config
from src.aml_workshop_simulator.domain.operation_purposes import validate_purpose


@lru_cache(maxsize=1)
def catalog():
    old, templates = previous_catalog()
    config = deepcopy(old)
    defaults = load_config('game_curriculum_defaults_v3.json')
    config['resources'] = deepcopy(defaults['resources'])
    config['objectives'] = deepcopy(defaults['objectives'])
    config['constraints'].update(defaults['constraints'])
    for operation in config['operations']:
        if operation['code'] in defaults['operation_limits']:
            operation['max_occurrences'] = defaults['operation_limits'][operation['code']]
    assert config['behavior'] == old['behavior']
    return config, templates


def split_one(steps, code, rng, seed, suffix):
    candidates = [i for i,s in enumerate(steps) if s['card']['code'] == code and Decimal(s['amount']) >= 20000]
    if not candidates:
        return
    index = rng.choice(candidates)
    original = steps[index]
    total = Decimal(original['amount'])
    part = max(Decimal('10000'), min(total-10000, (total*Decimal(str(rng.uniform(.3,.7)))).quantize(Decimal('.01'))))
    second = deepcopy(original)
    original['amount'] = str(part)
    second['amount'] = str(total-part)
    second['step_id'] = str(uuid5(NAMESPACE_URL, f'relaxed-v2/{seed}/{suffix}'))
    second['interval_minutes'] = rng.choice([1, 10, 60])
    steps.insert(index+1, second)


def candidate(seed):
    _, steps, family, topology = previous_candidate(seed)
    config, _ = catalog()
    rng = random.Random(seed ^ 0x927A61)
    # Keep an explicit unchanged-route control stratum (one quarter of seeds).
    if seed % 4 != 0:
        if rng.random() < .65:
            split_one(steps, 'incoming_transfer', rng, seed, 'receipt')
        for n in range(rng.choice([0, 1, 2, 3])):
            split_one(steps, 'card_transfer', rng, seed, f'debit-{n}')
    # One coherent declared transfer purpose per chain, independent of its label.
    purpose = rng.choice(['shared_expense', 'shared_expense', 'loan', 'refund', 'asset_sale', 'service_payment'])
    for step in steps:
        if step['card']['code'] in ('incoming_transfer', 'card_transfer'):
            step['purpose_code'] = purpose
        validate_purpose(step)
    return config, steps, family, topology
