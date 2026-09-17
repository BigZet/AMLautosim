"""Coverage repair: delayed settlement after receipts, independent of labels.

Half the original 15 route candidates place a one-day wait before the first
financial debit after each receipt episode. Other operations, resources, parties
and all teaching labels are unchanged. Full engine validation still applies.
"""
from scripts.aml_game_curriculum import candidate as original_candidate, catalog


def candidate(seed):
    config, steps, family, topology = original_candidate(seed)
    if family < 15 and (seed // len(catalog()[1])) % 2 == 0:
        pending = False
        for step in steps:
            code = step['card']['code']
            if code == 'incoming_transfer':
                pending = True
            elif pending and code in ('card_transfer', 'cash_withdrawal'):
                step['interval_minutes'] = 1440
                pending = False
    return config, steps, family, topology