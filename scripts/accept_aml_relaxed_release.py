"""Bind a relaxed release only after independent replay and gameplay gates pass."""
import argparse
import json
from pathlib import Path
from scripts.audit_aml_history_population import file_hash, require


def accept(dataset, model, comparison, gameplay_exception=None):
    audit=json.loads((dataset/'audit.json').read_bytes())
    replay=json.loads((dataset/'readback-audit.json').read_bytes())
    manifest=json.loads((model/'manifest.json').read_bytes())
    gameplay=json.loads((model/'gameplay-audit.json').read_bytes())
    coverage=json.loads(comparison.read_bytes())
    require(replay['passed'] and replay['rows']==audit['rows'], 'Dataset replay not accepted')
    require(manifest['offline_quality_passed'] and not manifest['failures'], 'Model quality failed')
    from src.aml_workshop_simulator.services.classifier_acceptance import gameplay_accepted
    require(gameplay_accepted(gameplay, file_hash(model/'gameplay-audit.json'), gameplay_exception), 'Gameplay gates failed')
    require(coverage['immutable_behavior'], 'Shared history changed')
    require(coverage['counts']['chains']==audit['rows'], 'Coverage does not describe full dataset')
    for key in ('newly_playable','four_receipts','over_eight_card_transfers','over_fourteen_actions',
                'incoming_over_80000','card_over_80000','cash_operation_over_100000','total_cash_over_120000'):
        require(coverage['counts'][key]>0, 'Missing coverage: '+key)
    for name,digest in audit['artifact_hashes'].items():
        require(file_hash(dataset/name)==digest, 'Artifact drift: '+name)
    require(manifest['dataset_hashes']==audit['artifact_hashes'], 'Model dataset mismatch')
    require(manifest['context_sha256']==audit['context_sha256']==gameplay['context_sha256'], 'Context mismatch')
    report=dict(ready_for_training=True,offline_release_accepted=True,live_game_switched=False,
                rows=audit['rows'], source_manifest_sha256=file_hash(dataset/'audit.json'),
                readback_sha256=file_hash(dataset/'readback-audit.json'),
                model_manifest_sha256=file_hash(model/'manifest.json'),
                gameplay_audit_sha256=file_hash(model/'gameplay-audit.json'),
                coverage_sha256=file_hash(comparison), coverage=coverage['counts'],
                metrics=manifest['metrics']['test'], preset='config/game_curriculum_defaults_v4.json',
                verifier_sha256=file_hash(__file__),
                limitations=['Synthetic teaching interpretations; no independent human AML validation',
                             'Unseen-seed checks share authored route families with training'])
    if gameplay_exception:
        report['gameplay_exception'] = gameplay_exception
    output=dataset/'acceptance.json'
    with output.open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset',type=Path)
    p.add_argument('model',type=Path)
    p.add_argument('--comparison',type=Path,required=True)
    a=p.parse_args()
    accept(a.dataset,a.model,a.comparison)
