"""Shared-history game at the new default target, with alternative funding paths."""
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
import random

from scripts.aml_game_curriculum_v4 import candidate as broad_candidate
from scripts.aml_game_curriculum import catalog as original_catalog
from src.aml_workshop_simulator.core.game_config import load_config


@lru_cache(maxsize=1)
def catalog():
    original, templates = original_catalog()
    config = deepcopy(original)
    defaults = load_config("game_curriculum_defaults_v1.json")
    config['objectives'] = deepcopy(defaults['objectives'])
    config['resources'] = deepcopy(defaults['resources'])
    assert config['objectives']['target_outflow'] == '360000.00'
    assert config['behavior']['history'] == original['behavior']['history']
    return config, templates


def allocate(steps, target, config):
    bounds = {c['code']: (Decimal(c['min_amount']), Decimal(c['max_amount'])) for c in config['card_snapshots']}
    financial = [s for s in steps if s['card']['code'] in ('card_transfer','cash_withdrawal')]
    total = sum(Decimal(s['amount']) for s in financial)
    for step in financial:
        lower, _ = bounds[step['card']['code']]
        step['amount'] = str(max(lower,(Decimal(step['amount'])*target/total).quantize(Decimal('.01'))))
    delta = target - sum(Decimal(s['amount']) for s in financial)
    for step in sorted(financial,key=lambda s: -Decimal(s['amount'])):
        lower, upper = bounds[step['card']['code']]
        amount = Decimal(step['amount'])
        change = min(delta,upper-amount) if delta >= 0 else -min(-delta,amount-lower)
        step['amount'] = str(amount+change)
        delta -= change
    assert delta == 0


def candidate(seed):
    _, steps, family, topology = broad_candidate(seed)
    config, templates = catalog()
    rng = random.Random(seed ^ 0x71CBA1)
    outflow = rng.choices([360000,380000,400000],[8,1,1])[0]
    allocate(steps,Decimal(outflow),config)
    if rng.random() < .7:
        bounds = {c['code']:(Decimal(c['min_amount']),Decimal(c['max_amount'])) for c in config['card_snapshots']}
        financial = [s for s in steps if s['card']['code'] in ('card_transfer','cash_withdrawal')]
        for _ in range(6):
            left, right = rng.sample(financial,2)
            delta = Decimal(rng.randint(-12000,12000))
            a, b = Decimal(left['amount'])+delta, Decimal(right['amount'])-delta
            la, ha = bounds[left['card']['code']]
            lb, hb = bounds[right['card']['code']]
            cash = sum(Decimal(s['amount']) for s in financial if s['card']['code'] == 'cash_withdrawal')
            cash += delta if left['card']['code'] == 'cash_withdrawal' else 0
            cash -= delta if right['card']['code'] == 'cash_withdrawal' else 0
            if la <= a <= ha and lb <= b <= hb and cash <= 120000:
                left['amount'], right['amount'] = str(a), str(b)
    if outflow == 360000 and rng.random() < .4:
        receipts = [i for i,s in enumerate(steps) if s['card']['code'] == 'incoming_transfer']
        if len(receipts) == 3:
            del steps[rng.choice(receipts)]
            salary = next((s for s in steps if s['card']['code'] == 'salary'),None)
            if salary is None:
                salary = deepcopy(templates[18][1][0])
                salary.update(sender_id='employer',purpose_code='salary',action_details={'income_basis':'payroll_registry'})
                steps.insert(0,salary)
            salary['amount'] = '30000'
            for index,step in enumerate(steps):
                if index == 0:
                    step['interval_minutes'] = None
                elif step.get('interval_minutes') is None:
                    step['interval_minutes'] = 1
                if step['card']['code'] == 'incoming_transfer':
                    step['amount'] = str(rng.randint(78000,80000))
    return config, steps, family, topology
