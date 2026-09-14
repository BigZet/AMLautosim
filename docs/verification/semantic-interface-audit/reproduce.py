"""Read-only semantic audit; writes evidence only to --output. No training/API calls."""
import argparse
import hashlib
import itertools
import json
import platform
from copy import deepcopy
from pathlib import Path

import catboost
import numpy as np
import pandas as pd
from catboost import Pool

from scripts.aml_dataset.expanded import label
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.aml_dataset_features_v3 import extract_features
from src.aml_workshop_simulator.services.aml_risk_model import AMLRiskModel
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.expanded_simulation import evaluate_expanded_scenario
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stats(x):
    a = np.asarray(x, dtype=float)
    return dict(n=len(a), min=float(a.min()), max=float(a.max()),
                mean=float(a.mean()), std=float(a.std()),
                quantiles=dict(zip(('p10', 'p25', 'p50', 'p75', 'p90'),
                                   map(float, np.quantile(a, [.1,.25,.5,.75,.9])))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).parent
    fixture = json.loads((here / 'fixtures.json').read_text())
    config = fixture['config']
    scenarios = fixture['strategies']
    model_dir = Path('resources/catboost_models/integration-v2-final')
    data = Path('resources/aml_dataset/behavior-v3/release')
    model = AMLRiskModel(model_dir)
    rules = json.loads((data / 'rubric.json').read_text())
    manifest = json.loads((model_dir / 'manifest.json').read_text())
    checks = {name: sha(data / name) == expected
              for name, expected in manifest['dataset_checksums'].items()}
    assert all(checks.values()), checks
    cards = {c['code']: c for c in config['card_snapshots']}
    prototypes = {s['card']['code']: s for r in scenarios for s in r['steps']}
    matrix = []
    for code, proto in prototypes.items():
        role = 'sender_id' if code in ('salary', 'incoming_transfer') else 'recipient_id'
        ids = [None] if code == 'cash_withdrawal' else [p['id'] for p in config['behavior']['counterparties']] + ['not-in-catalog']
        fields = [f for f in cards[code]['fields'] if f['key'] != 'sender_relationship']
        choices = [dict(zip([f['key'] for f in fields], vals)) for vals in
                   itertools.product(*[[o['value'] for o in f['options']] for f in fields])]
        for identity, details, channel in itertools.product(ids, choices, cards[code]['channels'] or [None]):
            s = deepcopy(proto)
            s.pop('sender_id', None)
            s.pop('recipient_id', None)
            if identity is not None:
                s[role] = identity
            s['action_details'] = details
            s['context'] = {'channel': channel} if channel else {}
            try:
                canonical_expanded_steps([s], config)
                accepted, reason = True, None
            except Exception as exc:
                accepted, reason = False, str(exc)
            matrix.append(dict(code=code, party=identity, details=details, channel=channel,
                               accepted=accepted, reason=reason))
    (args.output / 'operation-matrix.json').write_text(json.dumps(matrix, ensure_ascii=False, indent=2)+'\n')
    probes = {}
    for name, field, value in (
        ('client_supplied_relationship', 'action_details', {'sender_relationship': 'regular_sender'}),
        ('inapplicable_recipient', 'recipient_id', 'A'),
        ('invalid_channel', 'context', {'channel': 'atm'}),
    ):
        step = deepcopy(prototypes['incoming_transfer'])
        step[field] = value
        try:
            canonical_expanded_steps([step], config)
            probes[name] = 'accepted'
        except Exception:
            probes[name] = 'rejected'
    for name in ('future_history', 'unknown_history_party', 'purchase_wrong_party'):
        behavior = deepcopy(config['behavior'])
        if name == 'future_history':
            behavior['history']['operations'][0]['occurred_at'] = behavior['timeline']['starts_at']
        elif name == 'unknown_history_party':
            behavior['history']['operations'][0]['counterparty_id'] = 'not-in-catalog'
        else:
            next(o for o in behavior['history']['operations'] if o['operation_code'] == 'purchase')['counterparty_id'] = 'A'
        try:
            ExpandedBehavior.model_validate(behavior)
            probes[name] = 'accepted'
        except Exception:
            probes[name] = 'rejected'
    assert all(v == 'rejected' for v in probes.values()), probes
    rows, rubric_terms, features15 = [], [], []
    for r in scenarios:
        f = extract_features(r['steps'], config)
        features15.append(f)
        target, terms = label(f, rules)
        rubric_terms.append(dict(name=r['name'], target=target, terms=terms))
        pred = model.predict(r['steps'], config)
        saved = next(x for x in fixture['results'] if x['strategy'] == r['name'])
        rows.append(dict(name=r['name'], target=target, prediction=pred,
                         error=pred-target, saved_risk=saved['risk_score'],
                         game_score=saved['game_score'],
                         weighted_stealth=.65*(100-saved['risk_score']),
                         weighted_resources=saved['game_score']-.65*(100-saved['risk_score']),
                         history_stable_background=f['history_stable_background'],
                         income_basis=f['income_basis']))
    pd.DataFrame(rows).to_csv(args.output / 'strategies-comparison.csv', index=False)
    (args.output/'rubric-terms.json').write_text(json.dumps(rubric_terms, ensure_ascii=False, indent=2)+'\n')
    base = deepcopy(next(r['steps'] for r in scenarios if r['number'] == 6))
    before = extract_features(base, config)
    modified = deepcopy(config)
    modified['behavior']['profile']['description'] = 'Иное описание без изменения наблюдений'
    profile_equal = before == extract_features(base, modified)
    pair = deepcopy(base)
    debit = next(s for s in pair if s['card']['code'] == 'card_transfer')
    debit['card'] = {k: cards['cash_withdrawal'][k] for k in ('id','code','version')}
    debit.pop('recipient_id')
    debit['context'] = {}
    after = extract_features(pair, config)
    assert not submit_blockers(evaluate_expanded_scenario(pair, config))
    pair_evidence = dict(before=before['recipient_hhi'], after=after['recipient_hhi'],
                         recipients_before=before['unique_recipients'], recipients_after=after['unique_recipients'],
                         changed='One 80000 transfer replaced by 80000 cash withdrawal; sole remaining recipient unchanged',
                         both_goal_valid=True)
    frame = pd.read_csv(data / 'features.csv')
    split = pd.read_csv(data / 'split.csv')
    assert len(frame) == len(split) and split.row_index.tolist() == list(range(len(frame)))
    raw = model.model.predict(Pool(frame[model.columns], cat_features=model.schema['categorical']), thread_count=4)
    pred = np.clip(raw, 0, 100)
    distributions = {}
    for name in ('train', 'validation', 'test'):
        mask = split['split'].eq(name).to_numpy()
        y = frame.loc[mask, 'target_risk_score'].to_numpy()
        p = pred[mask]
        distributions[name] = dict(target=stats(y), prediction=stats(p),
                                   mae=float(np.abs(p-y).mean()), bias=float((p-y).mean()))
    findings = dict(python=platform.python_version(), catboost=catboost.__version__,
                    dataset_checksums_verified=checks,
                    fixture_sha256=sha(here/'fixtures.json'), model_sha256=sha(model_dir/'model.cbm'),
                    matrix_cases=len(matrix), matrix_accepted=sum(x['accepted'] for x in matrix),
                    profile_text_features_unchanged=profile_equal, concentration_pair=pair_evidence,
                    negative_probes=probes,
                    strategies_coverage={k: sorted(set(f[k] for f in features15)) for k in (
                        'history_known', 'history_count', 'history_stable_background', 'source_foreign_bank_kg_count',
                        'source_crypto_exchange_count', 'income_basis', 'night_share', 'target_outflow')},
                    strategies=dict(target=stats([r['target'] for r in rows]),
                                    prediction=stats([r['prediction'] for r in rows]),
                                    game=stats([r['game_score'] for r in rows]),
                                    mae=float(np.mean([abs(r['error']) for r in rows])),
                                    max_abs_error=max(abs(r['error']) for r in rows),
                                    max_saved_rounding_difference=max(abs(r['prediction']-r['saved_risk']) for r in rows)),
                    distributions=distributions)
    (args.output/'evidence.json').write_text(json.dumps(findings, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(findings, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
