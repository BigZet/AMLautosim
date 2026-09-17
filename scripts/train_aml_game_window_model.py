"""Train a shared classifier over observable temporal views; average class probabilities."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.linear_model import LogisticRegression
from scripts.train_aml_game_model import metrics
from scripts.audit_aml_history_population import file_hash, require
from scripts.aml_dataset import aml_population_author as author
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import PANEL_POLICY
from src.aml_workshop_simulator.services.aml_pattern_quality import QUALITY_POLICY, quality_failures
from src.aml_workshop_simulator.services.aml_game_window_model import FEATURES, views, interpretation_targets, raw_probabilities, calibrated


def weighted_views(rows, balanced=False):
    x = views(rows)
    p = interpretation_targets(x)
    require(np.allclose(p.reshape(3, len(rows)).mean(axis=0), rows.target_probability, atol=1e-12, rtol=0), 'Window target disagrees with frozen policy')
    factors = np.ones(len(rows))
    if balanced:
        counts = rows.route_family.value_counts()
        factors = (len(rows) / len(counts) / rows.route_family.map(counts)).to_numpy()
    factors = np.tile(factors, 3)
    weight = np.r_[p * factors, (1-p) * factors]
    keep = weight > 0
    return pd.concat([x, x], ignore_index=True).loc[keep, FEATURES], np.r_[np.ones(len(x)), np.zeros(len(x))][keep], weight[keep]


def train(dataset, output):
    require(not output.exists(), 'Output exists')
    audit = json.loads((dataset/'audit.json').read_bytes())
    readback = json.loads((dataset/'readback-audit.json').read_bytes())
    require(readback['passed'], 'Readback failed')
    for name, digest in audit['artifact_hashes'].items():
        require(file_hash(dataset/name) == digest, 'Dataset artifact drift')
    for name, digest in audit['source_hashes'].items():
        require(file_hash(name) == digest, 'Dataset source drift')
    require(audit['source_policy_sha256'] == author.digest(PANEL_POLICY), 'Policy drift')
    frame = pd.read_csv(dataset/'features.csv', float_precision='round_trip').merge(pd.read_csv(dataset/'targets.csv', float_precision='round_trip'), on='scenario_id', validate='one_to_one')
    require(frame.groupby('group_id').split.nunique().max() == 1, 'Group leakage')
    require(np.allclose(interpretation_targets(views(frame)).reshape(3,len(frame)).mean(axis=0), frame.target_probability, atol=1e-12, rtol=0), 'Full label equivalence failed')
    parts = {name: rows for name, rows in frame.groupby('split')}
    x, y, weight = weighted_views(parts['train'], balanced=True)
    vx, vy, vw = weighted_views(parts['validation'])
    model = CatBoostClassifier(iterations=1400, depth=8, learning_rate=.05, l2_leaf_reg=5,
                               random_seed=2026100400, thread_count=4, loss_function='Logloss',
                               verbose=False, allow_writing_files=False)
    model.fit(x, y, sample_weight=weight, eval_set=Pool(vx,vy,weight=vw), early_stopping_rounds=100, use_best_model=True)
    fit = parts['calibration-fit']
    probabilities = np.clip(raw_probabilities(model, fit), 1e-12, 1-1e-12)
    margin = np.log(probabilities/(1-probabilities))
    p = fit.target_probability.to_numpy()
    weights = np.r_[p,1-p]
    keep = weights > 0
    calibration_model = LogisticRegression(C=1.,random_state=2026100400)
    calibration_model.fit(np.r_[margin,margin].reshape(-1,1)[keep],np.r_[np.ones(len(p)),np.zeros(len(p))][keep],sample_weight=weights[keep])
    calibration = dict(method='sigmoid', a=float(calibration_model.coef_[0,0]), b=float(calibration_model.intercept_[0]))
    check = parts['calibration-check']
    raw = raw_probabilities(model, check)
    raw_metrics = metrics(check.target_probability, raw)
    cal_metrics = metrics(check.target_probability, calibrated(raw, calibration))
    if cal_metrics['expected_brier'] > raw_metrics['expected_brier'] or cal_metrics['expected_log_loss'] > raw_metrics['expected_log_loss']:
        calibration = dict(method='none')
    reports, predictions = {}, []
    for name, rows in parts.items():
        probability = calibrated(raw_probabilities(model,rows),calibration)
        reports[name] = metrics(rows.target_probability,probability)
        predictions.extend(dict(scenario_id=sid,split=name,probability=float(p)) for sid,p in zip(rows.scenario_id,probability))
    failures = quality_failures(reports['test'],representative=True)
    if reports['test']['mean_absolute_target_error'] > .03:
        failures.append('mean_absolute_target_error_above_0.03')
    output.mkdir(parents=True)
    model.save_model(str(output/'model.cbm'))
    pd.DataFrame(predictions).to_csv(output/'predictions.csv',index=False)
    manifest = dict(score_kind='educational_pattern_interpretation_probability', architecture='mean_of_three_shared_classifier_views',
                    features=FEATURES, panel_policy=PANEL_POLICY, context_sha256=audit['context_sha256'],dataset_hashes=audit['artifact_hashes'],
                    model_sha256=file_hash(output/'model.cbm'), calibration=calibration, calibration_comparison=dict(raw=raw_metrics,sigmoid=cal_metrics),
                    metrics=reports,quality_policy=QUALITY_POLICY,failures=failures,offline_quality_passed=not failures,release_ready=False,
                    training_weighting='Equal family contribution; view probabilities averaged using the three equal policy windows',
                    full_dataset_window_label_equivalence=True, trainer_sha256=file_hash(__file__),
                    inference_source_sha256=file_hash('src/aml_workshop_simulator/services/aml_game_window_model.py'),
                    limitations=['Synthetic interpretation target, not expert consensus or crime probability','Runtime integration and live-game acceptance remain separate'])
    (output/'manifest.json').write_bytes(author.json_bytes(manifest))
    print(json.dumps(dict(test=reports['test'], failures=failures)))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    train(args.dataset,args.output)