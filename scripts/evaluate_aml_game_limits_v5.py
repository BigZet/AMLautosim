"""Unseen-seed gameplay stress checks of a teaching-pattern classifier."""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from catboost import CatBoostClassifier
import numpy as np

from scripts.aml_game_curriculum import candidate as original_candidate
from scripts.aml_game_curriculum_v5 import candidate, catalog
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from scripts.aml_dataset import aml_population_author as author
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.domain.scoring import resource_score, probability_leaderboard_scores
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import extract_panel_features, assess_panel
from src.aml_workshop_simulator.core.errors import ValidationFailed


def valid(steps, config):
    try:
        return not submit_blockers(evaluate(steps, config))
    except ValidationFailed:
        return False


def run(package):
    manifest = json.loads((package / 'manifest.json').read_bytes())
    require(file_hash(package / 'model.cbm') == manifest['model_sha256'], 'Model drift')
    require(manifest['context_sha256'] == author.digest(catalog()[0]), 'Model/preset mismatch')
    model = CatBoostClassifier()
    model.load_model(str(package / 'model.cbm'))
    from src.aml_workshop_simulator.services.aml_game_window_model_v2 import score_features
    require(manifest['architecture'] == 'mean_of_three_shared_classifier_views', 'Wrong architecture')
    require(manifest['inference_source_sha256'] == file_hash('src/aml_workshop_simulator/services/aml_game_window_model_v2.py'), 'Inference source drift')
    def score(steps):
        return score_features(model, manifest, extract_panel_features(steps))

    low_families, low_resources, low_board = set(), set(), set()
    counts, max_cent_shift, max_target_error = Counter(), 0., 0.
    cases = []
    regressions = [2026200216, 2026200696, 2026201128, 2026200816, 2026200936, 2026300903, 2026301979, 2026301051, 2026301527, 2026302179, 2026300547]
    for seed in regressions + list(range(2040900000, 2040902400)):
        if seed in regressions:
            _, steps, family, _ = original_candidate(seed)
            config, _ = catalog()
        else:
            config, steps, family, _ = candidate(seed)
        snapshot = evaluate(steps, config)
        if submit_blockers(snapshot):
            continue
        counts['valid'] += 1
        codes = Counter(s['card']['code'] for s in steps)
        funding = f"{codes['incoming_transfer']}incoming_{codes['salary']}salary"
        counts['funding_' + funding] += 1
        value = score(steps)
        target = assess_panel(extract_panel_features(steps))['target_probability']
        max_target_error = max(max_target_error, abs(value - target))
        renamed = deepcopy(steps)
        for s in renamed:
            for field in ('sender_id', 'recipient_id'):
                if field in s:
                    s[field] = 'renamed-' + s[field]
        require(score(renamed) == value, 'ID renaming changes score')
        changed = deepcopy(steps)
        cards = [s for s in changed if s['card']['code'] == 'card_transfer']
        if len(cards) >= 2:
            cards[0]['amount'] = str(Decimal(cards[0]['amount']) + Decimal('.01'))
            cards[1]['amount'] = str(Decimal(cards[1]['amount']) - Decimal('.01'))
            if valid(changed, config):
                counts['cent_mutations_valid'] += 1
                max_cent_shift = max(max_cent_shift, abs(score(changed) - value))
        waited = deepcopy(steps)
        for s in waited[1:]:
            if s['card']['code'] in ('card_transfer', 'cash_withdrawal'):
                s['interval_minutes'] = 60
        if valid(waited, config):
            counts['waiting_valid'] += 1
            counts['waiting_still_high'] += score(waited) >= .9
        resources = resource_score(snapshot, config)
        board = probability_leaderboard_scores(value, resources, config)
        if value < .1:
            counts['low_funding_' + funding] += 1
            low_families.add(family)
            low_resources.add(float(resources))
            low_board.add(round(float(board['game_score']), 2))
        cases.append(dict(seed=seed, family=family, probability=value, target=target,
                          resource_score=float(resources), game_score=float(board['game_score']), funding=funding, regression=seed in regressions, steps=steps))
    failures = []
    if not counts['funding_2incoming_1salary'] or not counts['funding_3incoming_0salary']:
        failures.append('missing_alternative_funding_routes')
    if len(low_families) < 4:
        failures.append('fewer_than_four_low_strategies')
    if len(low_resources) < 10 or len(low_board) < 10:
        failures.append('insufficient_leaderboard_variety')
    if not counts['waiting_still_high']:
        failures.append('no_high_structural_patterns_after_valid_waits')
    if max_cent_shift > .1:
        failures.append('cent_mutation_probability_jump_above_0.1')
    if max_target_error > .25:
        failures.append('individual_probability_error_above_0.25')
    report = dict(context_sha256=manifest['context_sha256'], model_sha256=manifest['model_sha256'], counts=dict(counts), low_families=sorted(low_families),
                  distinct_low_resource_scores=len(low_resources), distinct_low_game_scores=len(low_board),
                  max_cent_probability_shift=max_cent_shift, max_target_error=max_target_error,
                  failures=failures, passed=not failures, script_sha256=file_hash(__file__),
                  note='Unseen seeds within authored route families; not independent human AML validation')
    report['largest_errors'] = [
        {k: r[k] for k in ('seed', 'family', 'probability', 'target')}
        for r in sorted(cases, key=lambda r: -abs(r['probability'] - r['target']))[:10]
    ]
    report['mean_absolute_target_error'] = float(np.mean([abs(r['probability'] - r['target']) for r in cases]))
    (package / 'gameplay-audit.json').write_bytes(author.json_bytes(report))
    (package / 'gameplay-cases.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in cases), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    run(parser.parse_args().package)
