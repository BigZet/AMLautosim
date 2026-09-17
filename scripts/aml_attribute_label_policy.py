"""Offline synthetic curriculum policy. Never imported by runtime inference.

Context adjusts interpretation strictness, not returned model probabilities.
Coefficients are authored teaching choices, not empirical AML likelihoods.
Strong structure remains decisive; changing a declaration cannot erase it.
"""
import numpy as np
from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import FEATURES

PANEL_POLICY = dict(version='aml-attribute-context-panel-v1', time_windows=[2,10,60],
                    sensitivity_settings=201, interpretations=603,
                    maximum_strictness_shift=.12,
                    meaning='Synthetic observable educational pattern membership; not criminal likelihood',
                    country_policy='Within-sender country changes only; RU and KG have equal status',
                    purpose_policy='Claims modify ambiguity only in combination with observable flow; no proof of legitimacy')


def interpretation_targets(frame):
    f = {name: frame[name].to_numpy()[:,None] for name in FEATURES}
    sensitivity = np.arange(201)[None,:]/200
    # More contextual inconsistency makes a marginal structural match easier;
    # coherent observed receipts/refunds make it harder. Total bounded at .12.
    adverse = (.025*f['rail_switch_rate'] + .02*f['country_switch_rate']
               + .02*f['transfer_channel_switch_rate'] + .015*f['cash_channel_switch_rate']
               + .02*f['purpose_switch_rate'] + .03*f['unsupported_refund_share']
               + .025*f['service_relay_share'] + .025*f['asset_cash_share']
               + .02*f['personal_passthrough_share'] + .015*f['funding_diversity']
               + .015*f['cash_purpose_switch_rate'])
    coherent = (.06*f['supported_refund_share'] + .04*f['shared_expense_alignment']
                + .04*f['salary_consumption_share'])
    strict = np.clip(sensitivity + np.clip(coherent-adverse,-.12,.12),0,1)
    votes = f['second_match_error'] <= .20-.16*strict
    votes |= (f['fanout']>=2)&(f['recipient_count']>=3)&(f['precredit_outflow_share']<.30-.10*strict)
    votes |= (f['cash']>=1)&(f['debit_episodes']>=2)&(f['cash_share']>=.15+.15*strict)
    votes |= (f['sender_count']>=np.where(strict<=2/3,2,3))&(f['max_recipient_share']>=.72+.20*strict)&(f['precredit_outflow_share']<.25-.10*strict)
    votes |= np.where(strict<=2/3,f['second_return_ratio_all'],f['third_return_ratio_all'])>=.45+.15*strict
    votes |= (f['card_count']>=7)&(f['second_split_ratio_all']<=.80-.15*strict)&(f['amount_repetition_strength']>=.65+.20*strict)
    return votes.mean(axis=1)


def assess_panel(features):
    import pandas as pd
    from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import views
    p=float(interpretation_targets(views(pd.DataFrame([features]))).mean())
    return dict(target_probability=p,positive_votes=int(round(603*p)),panel_size=603,
                band='low' if p<.1 else 'high' if p>=.9 else 'grey')
