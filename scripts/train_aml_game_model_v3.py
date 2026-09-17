"""Fit a CatBoost classifier to disclosed teaching-interpretation vote fractions."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.linear_model import LogisticRegression

from scripts.aml_dataset import aml_population_author as author
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import PANEL_POLICY
from src.aml_workshop_simulator.services.aml_pattern_quality import QUALITY_POLICY, quality_failures


def expand(frame, columns):
    p = frame.target_probability.to_numpy()
    x = pd.concat([frame[columns], frame[columns]], ignore_index=True)
    y = np.r_[np.ones(len(frame)), np.zeros(len(frame))]
    weights = np.r_[p, 1 - p]
    keep = weights > 0
    return x.loc[keep], y[keep], weights[keep]


def metrics(target, prediction):
    p = np.clip(np.asarray(prediction), 1e-12, 1 - 1e-12)
    target = np.asarray(target)
    low, high = p < .1, p >= .9
    return dict(
        rows=len(p),
        grey_row_share=float(np.mean(~low & ~high)),
        low_row_share=float(np.mean(low)), high_row_share=float(np.mean(high)),
        agreement=float(np.mean((p >= .5) == (target >= .5))),
        pattern_share_among_low=float(np.mean(target[low] >= .5)) if low.any() else None,
        nonpattern_share_among_high=float(np.mean(target[high] < .5)) if high.any() else None,
        mean_absolute_target_error=float(np.mean(abs(p - target))),
        target_mse=float(np.mean((p - target) ** 2)),
        expected_brier=float(np.mean(target * (1 - p) ** 2 + (1 - target) * p ** 2)),
        expected_log_loss=float(-np.mean(target * np.log(p) + (1 - target) * np.log(1 - p))),
    )


def train(dataset, output):
    require(not output.exists(), 'Model output already exists')
    audit = json.loads((dataset / 'audit.json').read_bytes())
    readback = json.loads((dataset / 'readback-audit.json').read_bytes())
    require(readback['passed'] and readback['rows'] == audit['rows'], 'Readback not passed')
    for name, digest in audit['artifact_hashes'].items():
        require(file_hash(dataset / name) == digest, 'Dataset artifact drift')
    for name, digest in audit['source_hashes'].items():
        require(file_hash(name) == digest, 'Dataset source drift')
    require(readback['audit_script_sha256'] == file_hash('scripts/audit_aml_game_dataset.py'),
            'Readback implementation changed')
    require(audit['source_policy_sha256'] == author.digest(PANEL_POLICY), 'Policy drift')
    features = pd.read_csv(dataset / 'features.csv')
    targets = pd.read_csv(dataset / 'targets.csv')
    frame = features.merge(targets, on='scenario_id', validate='one_to_one')
    require(frame.groupby('group_id')['split'].nunique().max() == 1, 'Group leakage')
    parts = {name: rows for name, rows in frame.groupby('split')}
    used = {'recipient_count', 'precredit_outflow_share', 'cash_share',
            'sender_count', 'max_recipient_share', 'second_return_ratio_all',
            'third_return_ratio_all', 'card_count', 'second_split_ratio_all',
            'amount_repetition_strength'}
    used.update(f'{prefix}_{window}' for prefix in
                ('second_match_error', 'fanout', 'cash', 'debit_episodes')
                for window in (2, 10, 60))
    columns = [c for c in features if c in used and parts['train'][c].nunique() > 1]
    model = CatBoostClassifier(iterations=1400, depth=8, learning_rate=.05,
                               l2_leaf_reg=5, random_seed=2026100400, thread_count=4,
                               loss_function='Logloss', verbose=False, allow_writing_files=False)
    x, y, weight = expand(parts['train'], columns)
    vx, vy, vw = expand(parts['validation'], columns)
    model.fit(x, y, sample_weight=weight, eval_set=Pool(vx, vy, weight=vw),
              early_stopping_rounds=100, use_best_model=True)
    fit = parts['calibration-fit']
    margins = model.predict(fit[columns], prediction_type='RawFormulaVal')
    expanded = np.r_[margins, margins].reshape(-1, 1)
    target = fit.target_probability.to_numpy()
    weights = np.r_[target, 1-target]
    keep = weights > 0
    calibrator = LogisticRegression(C=1., random_state=2026100400)
    calibrator.fit(expanded[keep], np.r_[np.ones(len(fit)), np.zeros(len(fit))][keep],
                   sample_weight=weights[keep])
    check = parts['calibration-check']
    margin = model.predict(check[columns], prediction_type='RawFormulaVal')
    raw = metrics(check.target_probability, model.predict_proba(check[columns])[:, 1])
    adjusted = metrics(check.target_probability, calibrator.predict_proba(margin.reshape(-1, 1))[:, 1])
    use_calibration = (adjusted['expected_brier'] <= raw['expected_brier'] and
                       adjusted['expected_log_loss'] <= raw['expected_log_loss'])
    reports, predictions = {}, []
    for split, rows in parts.items():
        margin = model.predict(rows[columns], prediction_type='RawFormulaVal')
        prediction = (calibrator.predict_proba(margin.reshape(-1, 1))[:, 1] if use_calibration
                      else model.predict_proba(rows[columns])[:, 1])
        reports[split] = metrics(rows.target_probability, prediction)
        predictions.extend(dict(scenario_id=sid, split=split, probability=float(value))
                           for sid, value in zip(rows.scenario_id, prediction))
    failures = quality_failures(reports['test'], representative=True)
    if reports['test']['mean_absolute_target_error'] > .03:
        failures.append('mean_absolute_target_error_above_0.03')
    output.mkdir(parents=True)
    model.save_model(str(output / 'model.cbm'))
    pd.DataFrame(predictions).to_csv(output / 'predictions.csv', index=False)
    manifest = dict(
        score_kind='educational_pattern_interpretation_probability',
        panel_policy=PANEL_POLICY, features=columns,
        context_sha256=audit['context_sha256'], dataset_hashes=audit['artifact_hashes'],
        model_sha256=file_hash(output / 'model.cbm'),
        calibration=dict(method='sigmoid' if use_calibration else 'none',
                         a=float(calibrator.coef_[0, 0]), b=float(calibrator.intercept_[0])),
        calibration_comparison=dict(raw=raw, sigmoid=adjusted), metrics=reports,
        quality_policy=QUALITY_POLICY, failures=failures,
        offline_quality_passed=not failures, release_ready=False,
        limitations=['Synthetic teaching interpretations, not independent experts',
                     'Gameplay stress evaluation and runtime integration still required'],
        trainer_sha256=file_hash(__file__),
    )
    (output / 'manifest.json').write_bytes(author.json_bytes(manifest))
    print(json.dumps(dict(test=reports['test'], failures=failures)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    train(args.dataset, args.output)
