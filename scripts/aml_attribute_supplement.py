"""Supplement existing authored chains with noninitial salary and all wait choices."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
from uuid import uuid5, NAMESPACE_URL

from scripts.aml_game_curriculum_v9 import catalog
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from scripts.aml_dataset import aml_population_author as author
from scripts.audit_aml_history_population import file_hash, require
from src.aml_workshop_simulator.domain.scoring import resource_score, probability_leaderboard_scores
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import extract_panel_features, assess_panel

BASE = Path('E:/AMLautosim-artifacts/aml-probability-v1/game-attributes-v1-60000')


def generate_family(task):
    key, count = task
    band = key.split(':')[0]
    config, _ = catalog()
    manifest = json.loads((BASE/'audit.json').read_bytes())
    require(manifest['rows'] == 60000, 'Unexpected source dataset')
    for name, digest in manifest['artifact_hashes'].items():
        require(file_hash(BASE/name) == digest, 'Source dataset drift')
    rows = []
    for line in (BASE/'casebook.jsonl').open(encoding='utf8'):
        row = json.loads(line)
        if row['band'] == band:
            row['features'] = extract_panel_features(row['steps'])
            rows.append(row)
    sources = [r for r in rows if r['steps'][0]['card']['code']=='salary']
    require(bool(sources), 'Missing salary source cases')
    rng = random.Random(2081900000 + {'low':0,'high':1,'grey':2}[band])
    rejected = Counter()
    initial = len(rows)
    seen = set()
    for attempt in range(200000):
        if len(rows) == count:
            print(json.dumps({'band':band,'base':initial,'salary_supplement':len(rows)-initial}),flush=True)
            return rows,dict(rejected)
        parent = rng.choice(sources)
        steps = deepcopy(parent['steps'])
        salary = steps.pop(0)
        position = rng.randint(1,min(4,len(steps)))
        salary['interval_minutes'] = rng.choice([1,10,60,1440])
        steps.insert(position,salary)
        steps[0]['interval_minutes'] = None
        features = extract_panel_features(steps)
        assessment = assess_panel(features)
        if assessment['band'] != band:
            rejected['supplement_band'] += 1
            continue
        observation = author.digest([{k:v for k,v in s.items() if k!='step_id'} for s in steps])
        if observation in seen:
            continue
        snapshot = evaluate(steps,config)
        blockers = submit_blockers(snapshot)
        if blockers:
            rejected.update(r['reason'] for r in blockers)
            continue
        seen.add(observation)
        sid = f'attributes-salary-{band}-{len(rows)-initial:04d}'
        for index,step in enumerate(steps):
            step['step_id'] = str(uuid5(NAMESPACE_URL,f'{sid}/{index}'))
        resources = resource_score(snapshot,config)
        board = probability_leaderboard_scores(assessment['target_probability'],resources,config)
        rows.append(dict(scenario_id=sid,source_scenario_id=parent['scenario_id'],seed=2081900000+attempt,
                         route_family=parent['route_family'],family_index=parent['family_index'],topology=parent['topology'],
                         steps=steps,features=features,**assessment,
                         resource_score=float(resources),reference_game_score=float(board['game_score'])))
    raise ValueError(f'Unable to fill salary supplement: {band} {len(rows)}/{count}')
