"""Replay every curriculum chain and independently check stored data and splits."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
import json
import math
from pathlib import Path

from scripts.aml_game_curriculum_v5 import catalog
from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.domain.scoring import (
    resource_score, probability_leaderboard_scores,
)
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
    PANEL_POLICY, extract_panel_features, assess_panel,
)


def replay(row):
    config, _ = catalog()
    require(row['context_sha256'] == p.digest(config), 'Context mismatch')
    snapshot = evaluate(row['steps'], config)
    require(not submit_blockers(snapshot), f"Invalid game chain: {row['scenario_id']}")
    features = extract_panel_features(row['steps'])
    target = assess_panel(features)
    for name, value in target.items():
        require(row[name] == value, f'Target mismatch: {name}')
    resources = resource_score(snapshot, config)
    require(row['resource_score'] == float(resources), 'Resource mismatch')
    board = probability_leaderboard_scores(target['target_probability'], resources, config)
    require(row['reference_game_score'] == float(board['game_score']), 'Leaderboard mismatch')
    return row['scenario_id'], features


def audit(dataset):
    manifest = json.loads((dataset / 'audit.json').read_bytes())
    for name, digest in manifest['artifact_hashes'].items():
        require(file_hash(dataset / name) == digest, f'Artifact drift: {name}')
    for name, digest in manifest['source_hashes'].items():
        require(file_hash(name) == digest, f'Source drift: {name}')
    require(manifest['source_policy_sha256'] == p.digest(PANEL_POLICY), 'Policy drift')
    require(json.loads((dataset / 'context.json').read_bytes()) == catalog()[0], 'Common context drift')
    with (dataset / 'targets.csv').open(encoding='utf8', newline='') as handle:
        targets = {r['scenario_id']: r for r in csv.DictReader(handle)}
    with (dataset / 'features.csv').open(encoding='utf8', newline='') as handle:
        features = {r['scenario_id']: r for r in csv.DictReader(handle)}
    groups, vectors, seen = {}, {}, set()
    with (dataset / 'casebook.jsonl').open(encoding='utf8') as handle, ProcessPoolExecutor(max_workers=4) as pool:
        rows = [json.loads(line) for line in handle]
        observations = set()
        for row in rows:
            key = p.digest([{k:v for k,v in s.items() if k != 'step_id'} for s in row['steps']])
            require(key not in observations, 'Duplicate exact observable chain')
            observations.add(key)
            target = targets[row['scenario_id']]
            for field in ('target_probability', 'positive_votes', 'panel_size', 'resource_score', 'reference_game_score'):
                require(math.isclose(float(target[field]), row[field], rel_tol=1e-12, abs_tol=1e-12),
                        f'Target table mismatch: {field}')
            require(target['band'] == row['band'], 'Band mismatch')
        for sid, actual in pool.map(replay, rows, chunksize=64):
            require(sid not in seen, 'Duplicate scenario ID')
            seen.add(sid)
            expected = {k: float(v) for k, v in features[sid].items() if k != 'scenario_id'}
            require(actual == expected, f'Features mismatch: {sid}')
            target = targets[sid]
            split = target['split']
            group = target['group_id']
            require(groups.setdefault(group, split) == split, 'Group split leakage')
            key = p.digest(actual)
            require(vectors.setdefault(key, (split, target['target_probability'])) ==
                    (split, target['target_probability']), 'Feature leakage or conflicting target')
    require(seen == set(features) == set(targets), 'Table coverage mismatch')
    require(len(seen) == manifest['rows'], 'Row count mismatch')
    graph = json.loads((dataset / 'groups.json').read_bytes())
    require(set(graph['scenario_groups']) == seen, 'Group graph coverage mismatch')
    for sid in seen:
        require(graph['scenario_groups'][sid] == targets[sid]['group_id'], 'Group graph mismatch')
    report = dict(passed=True, rows=len(seen), groups=len(groups),
                  split_bands={split: dict(Counter(r['band'] for r in targets.values() if r['split'] == split))
                               for split in sorted(set(groups.values()))},
                  checked=['all game constraints', 'immutable context', 'full feature replay',
                           'interpretation votes', 'actual leaderboard formula', 'source and artifact hashes',
                           'group and exact feature isolation', 'target consistency'],
                  independent_human_label_review=False,
                  audit_script_sha256=file_hash(__file__))
    (dataset / 'readback-audit.json').write_bytes(p.json_bytes(report))
    print(json.dumps(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    audit(parser.parse_args().dataset)
