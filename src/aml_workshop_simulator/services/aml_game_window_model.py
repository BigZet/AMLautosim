"""Observable time-window views of the fixed teaching-interpretation target."""
import numpy as np
import pandas as pd

BASE = ['recipient_count', 'precredit_outflow_share', 'cash_share', 'sender_count',
        'max_recipient_share', 'second_return_ratio_all', 'third_return_ratio_all',
        'card_count', 'second_split_ratio_all', 'amount_repetition_strength']
TEMPORAL = ['second_match_error', 'fanout', 'cash', 'debit_episodes']
FEATURES = BASE + TEMPORAL
WINDOWS = (2, 10, 60)


def views(frame):
    return pd.concat([frame[BASE + [f'{p}_{w}' for p in TEMPORAL]].rename(
        columns={f'{p}_{w}': p for p in TEMPORAL}) for w in WINDOWS], ignore_index=True)


def interpretation_targets(frame):
    # Training targets only. Never included in model inputs or runtime inference.
    sensitivity = np.arange(201)[None, :] / 200
    f = {name: frame[name].to_numpy()[:, None] for name in FEATURES}
    votes = f['second_match_error'] <= .20 - .16 * sensitivity
    votes |= (f['fanout'] >= 2) & (f['recipient_count'] >= 3) & (f['precredit_outflow_share'] < .30 - .10 * sensitivity)
    votes |= (f['cash'] >= 1) & (f['debit_episodes'] >= 2) & (f['cash_share'] >= .15 + .15 * sensitivity)
    votes |= (f['sender_count'] >= np.where(sensitivity <= 2/3, 2, 3)) & (f['max_recipient_share'] >= .72 + .20 * sensitivity) & (f['precredit_outflow_share'] < .25 - .10 * sensitivity)
    votes |= np.where(sensitivity <= 2/3, f['second_return_ratio_all'], f['third_return_ratio_all']) >= .45 + .15 * sensitivity
    votes |= (f['card_count'] >= 7) & (f['second_split_ratio_all'] <= .80 - .15 * sensitivity) & (f['amount_repetition_strength'] >= .65 + .20 * sensitivity)
    return votes.mean(axis=1)


def raw_probabilities(model, frame):
    values = model.predict_proba(views(frame)[FEATURES])[:, 1]
    return values.reshape(3, len(frame)).mean(axis=0)


def calibrated(values, calibration):
    if calibration['method'] == 'none':
        return values
    values = np.clip(values, 1e-12, 1 - 1e-12)
    z = calibration['a'] * np.log(values / (1 - values)) + calibration['b']
    return 1 / (1 + np.exp(-np.clip(z, -700, 700)))


def score_features(model, manifest, features):
    return float(calibrated(raw_probabilities(model, pd.DataFrame([features])), manifest['calibration'])[0])