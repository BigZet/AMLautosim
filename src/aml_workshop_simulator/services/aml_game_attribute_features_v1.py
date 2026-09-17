"""Observable relationships between transaction attributes, never labels.

No country, channel, counterparty name or declared purpose is a risk weight.
Renaming parties, channels or countries consistently preserves relationships.
"""
from collections import defaultdict
import pandas as pd
from .aml_game_pattern_panel_v2 import extract_panel_features as structural_features
from .aml_game_window_model_v2 import FEATURES as STRUCTURAL, WINDOWS, views as structural_views, calibrated

CONTEXT_FEATURES = [
    'rail_switch_rate', 'country_switch_rate', 'transfer_channel_switch_rate',
    'cash_channel_switch_rate', 'purpose_switch_rate', 'unsupported_refund_share',
    'supported_refund_share', 'shared_expense_alignment', 'service_relay_share',
    'asset_cash_share', 'personal_passthrough_share', 'salary_consumption_share',
    'funding_diversity', 'cash_purpose_switch_rate',
]
FEATURES = STRUCTURAL + CONTEXT_FEATURES
EXTRACTOR_VERSION = 'aml-game-attributes-context-v1'


def switch_rate(values):
    return sum(a != b for a, b in zip(values, values[1:])) / max(1, len(values)-1)


def extract_panel_features(steps):
    result = structural_features(steps)
    incoming = [s for s in steps if s['card']['code'] == 'incoming_transfer']
    cards = [s for s in steps if s['card']['code'] == 'card_transfer']
    cash = [s for s in steps if s['card']['code'] == 'cash_withdrawal']
    total_cards = sum(float(s['amount']) for s in cards)
    total_cash = sum(float(s['amount']) for s in cash)
    total_credit = sum(float(s['amount']) for s in steps if s['card']['code'] in ('incoming_transfer', 'salary'))
    purchases = sum(float(s['amount']) for s in steps if s['card']['code'] == 'purchase'
                    and s['purpose_code'] in ('personal_spending','service_payment'))
    salary = sum(float(s['amount']) for s in steps if s['card']['code'] == 'salary'
                 and s.get('action_details', {}).get('income_basis') == 'payroll_registry')
    rails = [s['action_details']['incoming_kind'] for s in incoming]
    countries = defaultdict(list)
    for s in incoming:
        if s['action_details']['incoming_kind'] == 'bank_transfer':
            countries[s['sender_id']].append(s['action_details']['bank_country'])
    country_pairs = sum(max(0, len(v)-1) for v in countries.values())
    country_switches = sum(sum(a != b for a,b in zip(v,v[1:])) for v in countries.values())
    purposes = defaultdict(list)
    for s in steps:
        if s['card']['code'] != 'cash_withdrawal':
            purposes[s['card']['code']].append(s['purpose_code'])
    purpose_pairs = sum(max(0,len(v)-1) for v in purposes.values())
    purpose_switches = sum(sum(a != b for a,b in zip(v,v[1:])) for v in purposes.values())
    supported, unsupported, shared, service, asset_cash, personal = (0.,)*6
    # Remaining observed receipts are consumed once by a declared refund.
    refundable = defaultdict(float)
    receipt = None
    elapsed = 0
    for s in steps:
        elapsed += s.get('interval_minutes') or 0
        code, amount = s['card']['code'], float(s['amount'])
        if code == 'incoming_transfer':
            refundable[s['sender_id']] += amount
            receipt = (s, elapsed)
        elif code == 'card_transfer' and s['purpose_code'] == 'refund':
            covered = min(amount, refundable[s['recipient_id']])
            refundable[s['recipient_id']] -= covered
            supported += covered
            unsupported += amount-covered
        if receipt and code in ('card_transfer','cash_withdrawal'):
            source, at = receipt
            if elapsed-at <= 60:
                if source['purpose_code'] == 'shared_expense' and s['purpose_code'] == 'shared_expense' and code == 'card_transfer':
                    shared += amount
                if source['purpose_code'] == 'service_payment' and code == 'card_transfer' and s['recipient_id'] != source['sender_id']:
                    service += amount
                if source['action_details']['incoming_kind'] in ('crypto_p2p','exchange_withdrawal') and code == 'cash_withdrawal':
                    asset_cash += amount
                if s['purpose_code'] == 'personal_spending' and code == 'card_transfer':
                    personal += amount
    result.update(
        rail_switch_rate=switch_rate(rails), country_switch_rate=country_switches/max(1,country_pairs),
        transfer_channel_switch_rate=switch_rate([s.get('context',{}).get('channel','mobile') for s in cards]),
        cash_channel_switch_rate=switch_rate([s.get('context',{}).get('channel','atm') for s in cash]),
        purpose_switch_rate=purpose_switches/max(1,purpose_pairs),
        cash_purpose_switch_rate=switch_rate([s['purpose_code'] for s in cash]),
        unsupported_refund_share=unsupported/max(1,total_cards), supported_refund_share=supported/max(1,total_cards),
        shared_expense_alignment=shared/max(1,total_cards), service_relay_share=service/max(1,total_cards),
        asset_cash_share=asset_cash/max(1,total_cash), personal_passthrough_share=personal/max(1,total_cards),
        salary_consumption_share=min(salary,purchases)/max(1,total_credit),
        funding_diversity=max(0,len(set(rails))-1)/3,
    )
    return result


def views(frame):
    return pd.concat([structural_views(frame).reset_index(drop=True),
                      pd.concat([frame[CONTEXT_FEATURES]]*len(WINDOWS),ignore_index=True)],axis=1)[FEATURES]


def raw_probabilities(model, frame):
    values = model.predict_proba(views(frame), thread_count=4)[:,1]
    return values.reshape(len(WINDOWS),len(frame)).mean(axis=0)


def score_features(model, manifest, features):
    return float(calibrated(raw_probabilities(model,pd.DataFrame([features])),manifest['calibration'])[0])
