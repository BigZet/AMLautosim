"""Unseen-seed gameplay stress checks of a teaching-pattern classifier."""

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

from catboost import CatBoostClassifier
import numpy as np

from scripts.aml_game_curriculum_v9 import candidate as base_candidate, catalog
from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import score_features
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from scripts.aml_dataset import aml_population_author as author
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.domain.scoring import resource_score, probability_leaderboard_scores
from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import extract_panel_features
from scripts.aml_attribute_label_policy import assess_panel
from src.aml_workshop_simulator.core.errors import ValidationFailed


def candidate(seed):
    config, steps, family, topology = base_candidate(seed)
    if steps[0]['card']['code'] == 'salary' and seed % 2:
        salary = steps.pop(0)
        salary['interval_minutes'] = [1, 10, 60, 1440][(seed // 2) % 4]
        steps.insert(1 + (seed // 8) % min(4, len(steps)), salary)
        steps[0]['interval_minutes'] = None
    return config, steps, family, topology


def valid(steps, config):
    try:
        return not submit_blockers(evaluate(steps, config))
    except ValidationFailed:
        return False


def run(package, seed_start=2071900000, seed_count=5000):
    manifest = json.loads((package / 'manifest.json').read_bytes())
    require(file_hash(package / 'model.cbm') == manifest['model_sha256'], 'Model drift')
    model = CatBoostClassifier()
    model.load_model(str(package / 'model.cbm'))
    def score(steps):
        return score_features(model, manifest, extract_panel_features(steps))
    low_families, low_resources, low_board = set(), set(), set()
    counts, max_cent_shift, max_target_error = Counter(), 0., 0.
    cases = []
    for seed in range(seed_start, seed_start+seed_count):
        config, steps, family, _ = candidate(seed)
        snapshot = evaluate(steps, config)
        if submit_blockers(snapshot):
            continue
        counts['valid'] += 1
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
            cards[0]['amount'] = str(Decimal(str(cards[0]['amount'])) + Decimal('.01'))
            cards[1]['amount'] = str(Decimal(str(cards[1]['amount'])) - Decimal('.01'))
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
            low_families.add(family)
            low_resources.add(float(resources))
            low_board.add(round(float(board['game_score']), 2))
        cases.append(dict(seed=seed, family=family, probability=value, target=target,
                          resource_score=float(resources), game_score=float(board['game_score']), steps=steps))
    failures = []
    if len(low_families) < 4:
        failures.append('fewer_than_four_low_strategies')
    if len(low_resources) < 10 or len(low_board) < 10:
        failures.append('insufficient_leaderboard_variety')
    if not counts['waiting_still_high']:
        failures.append('no_high_structural_patterns_after_valid_waits')
    if max_cent_shift > .1:
        failures.append('cent_mutation_probability_jump_above_0.1')
    above_tolerance = [r for r in cases if abs(r['probability']-r['target']) > .25]
    if len(above_tolerance) > 20:
        failures.append('more_than_20_chains_above_probability_error_0.25')
    if seed_count != 5000 or counts['valid'] < 1500:
        failures.append('incomplete_full_stress_sample')
    report = dict(seed_start=seed_start,seed_count=seed_count,context_sha256=author.digest(catalog()[0]), counts=dict(counts), low_families=sorted(low_families),
                  distinct_low_resource_scores=len(low_resources), distinct_low_game_scores=len(low_board),
                  max_cent_probability_shift=max_cent_shift, max_target_error=max_target_error,
                  failures=failures, passed=not failures, script_sha256=file_hash(__file__),
                  note='Unseen seeds within authored route families; not independent human AML validation')
    report['largest_errors'] = [
        {k: r[k] for k in ('seed', 'family', 'probability', 'target')}
        for r in sorted(cases, key=lambda r: -abs(r['probability'] - r['target']))[:10]
    ]
    report['mean_absolute_target_error'] = float(np.mean([abs(r['probability'] - r['target']) for r in cases]))
    report['error_tolerance_policy'] = dict(absolute_probability_error=.25,maximum_chains_above_tolerance=20,
        actual_chains_above_tolerance=len(above_tolerance),required_candidate_seeds=5000,minimum_valid_chains=1500,
        approval='explicit_user_instruction',user_statement='До 20 цепочек выше допуска норма')
    report['above_tolerance_cases'] = [{k:r[k] for k in ('seed','family','probability','target')} for r in above_tolerance]
    (package / 'gameplay-audit.json').write_bytes(author.json_bytes(report))
    (package / 'gameplay-cases.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in cases), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--seed-start',type=int,default=2071900000)
    parser.add_argument('--seed-count',type=int,default=5000)
    a=parser.parse_args()
    run(a.package,a.seed_start,a.seed_count)
