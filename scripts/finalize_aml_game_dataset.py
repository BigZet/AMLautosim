"""Publish dataset acceptance only after full replay and model/gameplay gates."""
import argparse
import json
from pathlib import Path
import pandas as pd
from scripts.audit_aml_history_population import file_hash, require
from scripts.aml_dataset import aml_population_author as author


def finalize(dataset, model, examples, report_dir):
    audit = json.loads((dataset / 'audit.json').read_bytes())
    readback = json.loads((dataset / 'readback-audit.json').read_bytes())
    manifest = json.loads((model / 'manifest.json').read_bytes())
    gameplay = json.loads((model / 'gameplay-audit.json').read_bytes())
    for name, digest in audit['artifact_hashes'].items():
        require(file_hash(dataset / name) == digest, 'Artifact drift: ' + name)
    for name, digest in audit['source_hashes'].items():
        require(file_hash(name) == digest, 'Source drift: ' + name)
    require(manifest.get('full_dataset_window_label_equivalence'), 'Window target equivalence missing')
    require(manifest['inference_source_sha256'] == file_hash('src/aml_workshop_simulator/services/aml_game_window_model_v2.py'), 'Inference drift')
    require(manifest['trainer_sha256'] == file_hash(manifest.get('trainer_path', 'scripts/train_aml_game_window_model_v2.py')), 'Trainer drift')
    require(gameplay['script_sha256'] == file_hash('scripts/evaluate_aml_game_limits_v5.py'), 'Gameplay implementation drift')
    require(readback['audit_script_sha256'] == file_hash('scripts/audit_aml_game_dataset_v5.py'), 'Replay implementation drift')
    require(gameplay['model_sha256'] == manifest['model_sha256'], 'Gameplay/model mismatch')
    require(gameplay['context_sha256'] == manifest['context_sha256'] == audit['context_sha256'], 'Preset mismatch')
    require(readback['passed'] and readback['rows'] == audit['rows'], 'Full replay missing')
    require(manifest['dataset_hashes'] == audit['artifact_hashes'], 'Model/dataset mismatch')
    require(manifest['offline_quality_passed'] and not manifest['failures'], 'Model quality failed')
    require(gameplay['passed'] and not gameplay['failures'], 'Gameplay failed')
    require(file_hash(model / 'model.cbm') == manifest['model_sha256'], 'Model drift')
    require(examples.read_text(encoding='utf8').count('### ') == 25, 'Missing examples')
    cases = [json.loads(s) for s in (dataset / 'casebook.jsonl').read_text(encoding='utf8').splitlines()]
    standalone = sum(set(r['rule_support']) == {'fragmentation'} for r in cases)
    require(standalone > 0, 'Standalone fragmentation missing')
    require(len(audit['rule_positive_votes']) == 6, 'Pattern coverage incomplete')
    frame = pd.read_csv(dataset / 'features.csv').merge(pd.read_csv(dataset / 'targets.csv'), on='scenario_id')
    low_incoming_first = int(((frame.split == 'train') & (frame.target_probability < .1) & (frame.precredit_outflow_share == 0)).sum())
    require(low_incoming_first >= 20, 'Incoming-first negative coverage insufficient')
    require(len((model / 'gameplay-cases.jsonl').read_text(encoding='utf8').splitlines()) == gameplay['counts']['valid'], 'Stress artifact incomplete')
    result = dict(ready_for_training=True, live_game_switched=False, rows=audit['rows'],
                  preset='config/game_curriculum_defaults_v1.json',
                  target='observable educational AML patterns, not proven crime',
                  source_manifest_sha256=file_hash(dataset / 'audit.json'),
                  readback_sha256=file_hash(dataset / 'readback-audit.json'),
                  model_manifest_sha256=file_hash(model / 'manifest.json'),
                  gameplay_audit_sha256=file_hash(model / 'gameplay-audit.json'),
                  examples_sha256=file_hash(examples),
                  low_incoming_first_train_rows=low_incoming_first,
                  standalone_fragmentation_rows=standalone,
                  metrics=manifest['metrics']['test'], gameplay=gameplay,
                  limitations=['Authored synthetic teaching population, not player prevalence',
                               'Base 60000 rows: 42.5% low, 42.5% high, 15% grey; plus an unstratified concentration grid',
                               '603 correlated programmed interpretations, not independent experts',
                               'Test families are shared with training; no unseen-typology validation',
                               'Earlier test/stress findings informed revisions; these are development metrics',
                               'Runtime integration and human gameplay acceptance remain unfinished'],
                  verifier_sha256=file_hash(__file__))
    report_dir.mkdir(parents=True, exist_ok=True)
    (dataset / 'acceptance.json').write_bytes(author.json_bytes(result))
    (report_dir / 'game-curriculum-acceptance-2026-09-17.json').write_bytes(author.json_bytes(result))
    m = result['metrics']
    text = f"""# AML game curriculum: {dataset.name}

Status: prepared and checked for training; NOT connected to the live game.

- {audit['rows']} valid chains; one immutable shared history/profile.
- New preset: target 360000, initial balance 180000, energy/time 30/30, max 14 actions.
- The legacy v8 game retains its 400000 contract. Leaderboard weights stay 65/35.
- Test grey predictions: {m['grey_row_share']:.2%}; required 10-20%.
- Agreement with teaching interpretations: {m['agreement']:.2%}.
- Mean absolute target error: {m['mean_absolute_target_error']:.6f}.
- Low-score stress families: {len(gameplay['low_families'])}; distinct low leaderboard results: {gameplay['distinct_low_game_scores']}.
- Incoming-first low training chains: {low_incoming_first}; standalone fragmentation: {standalone}.

## Meaning and limits

Targets are fractions of 603 programmed interpretations of observable teaching
patterns, not empirical fraud probabilities or human consensus. The curriculum
starts with 60000 rows selected as 42.5% low, 42.5% high and 15% grey targets BEFORE
fitting. It then adds a feasible concentration grid without target-band selection.
No model predictions select rows. No label flipping or score stretching.
This is not player prevalence. Exact final band counts are in audit.json.

CatBoostClassifier uses weighted binary copies (p and 1-p); three time-window
probabilities are averaged. Policy-informed inactive-feature normalization
preserves every target. Inference uses model probabilities, never label rules.
Related chains and equal feature vectors stay together in one split.

Earlier errors informed revisions. Families overlap between train/test. Results
are development evidence, not a blind external AML study or a human playtest.
Feasible funding alternatives do not establish equal competitive strength.

## Artifacts and reproduction

Immutable files: context.json, policy.json, casebook.jsonl, features.csv,
targets.csv, groups.json. Raw/final datasets share some files through hardlinks:
do not edit those files in place. readback-audit.json replays every row;
acceptance.json binds the model, stress checks, source hashes and examples.

Run from the repository worktree using new empty output directories:

```powershell
python -m scripts.build_aml_game_dataset_v5 --output RAW_DIR --count 60000
python -m scripts.split_aml_game_dataset_v3 RAW_DIR BASE_DATASET_DIR
python -m scripts.extend_aml_game_concentration BASE_DATASET_DIR EXTENDED_RAW_DIR
python -m scripts.split_aml_game_dataset_v3 EXTENDED_RAW_DIR DATASET_DIR
python -m scripts.audit_aml_game_dataset_v5 DATASET_DIR
python -m scripts.train_aml_game_window_model_v3 DATASET_DIR --output MODEL_DIR
python -m scripts.evaluate_aml_game_limits_v5 MODEL_DIR
python -m scripts.export_aml_game_examples DATASET_DIR MODEL_DIR EXAMPLES_MD
python -m scripts.finalize_aml_game_dataset --dataset DATASET_DIR --model MODEL_DIR --examples EXAMPLES_MD --report-dir REPORT_DIR
```

Model used: `{model}`. Examples: `{examples}`.
"""
    (dataset / 'README.md').write_text(text, encoding='utf8')
    print(json.dumps(dict(rows=audit['rows'], ready_for_training=True, metrics=m)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--examples', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    finalize(args.dataset, args.model, args.examples, args.report_dir)
