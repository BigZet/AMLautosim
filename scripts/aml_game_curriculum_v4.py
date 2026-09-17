"""Broader legal amount allocations without changing history or game rules."""
import random
from scripts.aml_game_curriculum_v3 import candidate as narrow_candidate, catalog as catalog


def candidate(seed):
    config, steps, family, topology = narrow_candidate(seed)
    rng = random.Random(seed ^ 0x61A4B2)
    if rng.random() < .70:
        outflows = [s for s in steps if s['card']['code'] in ('card_transfer', 'cash_withdrawal')]
        for _ in range(12):
            left, right = rng.sample(outflows, 2)
            delta = rng.randint(-15000, 15000)
            a, b = int(float(left['amount'])) + delta, int(float(right['amount'])) - delta
            left_max = 80000 if left['card']['code'] == 'card_transfer' else 100000
            right_max = 80000 if right['card']['code'] == 'card_transfer' else 100000
            if not (10000 <= a <= left_max and 10000 <= b <= right_max):
                continue
            cash = sum(int(float(s['amount'])) for s in outflows if s['card']['code'] == 'cash_withdrawal')
            cash += (delta if left['card']['code'] == 'cash_withdrawal' else 0)
            cash -= (delta if right['card']['code'] == 'cash_withdrawal' else 0)
            if cash > 120000:
                continue
            left['amount'], right['amount'] = str(a), str(b)
        if rng.random() < .5:
            for step in steps:
                if step['card']['code'] == 'incoming_transfer':
                    step['amount'] = str(rng.randint(75000, 80000))
    return config, steps, family, topology
