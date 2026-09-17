"""Sample every selectable operation attribute within the fixed game context."""
import random

from scripts.aml_game_curriculum_v8 import candidate as previous_candidate, catalog as catalog
from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes
from src.aml_workshop_simulator.services.semantic_contract import INCOMING_KINDS, BANK_COUNTRIES


def candidate(seed):
    config, steps, family, topology = previous_candidate(seed)
    rng = random.Random(seed ^ 0xAD917)
    channels = {c['code']: c['channels'] for c in config['card_snapshots']}
    for index, step in enumerate(steps):
        code = step['card']['code']
        if code == 'incoming_transfer':
            kind = rng.choice(tuple(INCOMING_KINDS))
            step['action_details'] = {'incoming_kind': kind}
            if kind == 'bank_transfer':
                step['action_details']['bank_country'] = rng.choice(tuple(BANK_COUNTRIES))
            if kind == 'exchange_withdrawal':
                step['sender_id'] = 'exchange'
        if channels[code]:
            step.setdefault('context', {})['channel'] = rng.choice(channels[code])
        step['purpose_code'] = rng.choice(allowed_purposes(step))
        # Preserve route timing in most cases; independently cover waits for rare cards.
        if index and rng.random() < .12:
            step['interval_minutes'] = int(rng.choice(tuple(config['behavior']['timeline']['waiting_costs'])))
        step['claim_id'] = None  # This fixed context exposes no selectable transaction facts.
    return config, steps, family, topology
