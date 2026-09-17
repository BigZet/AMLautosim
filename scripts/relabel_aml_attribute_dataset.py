"""Re-extract and relabel an immutable accepted corpus, preserving group splits."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from scripts.audit_aml_history_population import file_hash, require
from scripts.aml_dataset import aml_population_author as author
from scripts.aml_attribute_label_policy import PANEL_POLICY, interpretation_targets
from src.aml_workshop_simulator.services.aml_game_attribute_features_v1 import extract_panel_features, views
from src.aml_workshop_simulator.services.aml_context import canonical_steps


def build(source, output, reuse_canonical=False):
    require(not output.exists(), 'Output exists')
    old = json.loads((source/'audit.json').read_bytes())
    replay = json.loads((source/'readback-audit.json').read_bytes())
    require(replay['passed'] and replay['rows']==old['rows'], 'Source replay failed')
    for name,digest in old['artifact_hashes'].items():
        require(file_hash(source/name)==digest,'Source drift: '+name)
    output.mkdir(parents=True)
    for name in ('context.json','groups.json'):
        shutil.copyfile(source/name,output/name)
    config=json.loads((source/'context.json').read_bytes())
    target=pd.read_csv(source/'targets.csv',float_precision='round_trip').set_index('scenario_id')
    require(target.groupby('group_id').split.nunique().max()==1,'Group leakage')
    features, rows=[],[]
    with (source/'casebook.jsonl').open(encoding='utf8') as handle:
        for line in handle:
            row=json.loads(line)
            steps=row['steps'] if reuse_canonical else canonical_steps(row['steps'],config)
            features.append(dict(scenario_id=row['scenario_id'],**extract_panel_features(steps)))
            rows.append(row)
    frame=pd.DataFrame(features)
    probabilities=[]
    for start in range(0,len(frame),2000):
        batch=frame.iloc[start:start+2000]
        probabilities.extend(interpretation_targets(views(batch)).reshape(3,len(batch)).mean(axis=0))
    changed=0
    with (output/'casebook.jsonl').open('x',encoding='utf8') as handle:
        for row,p in zip(rows,probabilities):
            sid=row['scenario_id']
            changed+=abs(p-float(target.loc[sid,'target_probability']))>1e-12
            band='low' if p<.1 else 'high' if p>=.9 else 'grey'
            row.update(target_probability=float(p),positive_votes=int(round(p*603)),panel_size=603,
                       band=band,rule_support={'contextual_panel_votes':int(round(p*603))})
            # Resource result is unchanged; refresh the reference leaderboard.
            row['reference_game_score']=round(.65*(1-p)*100+.35*float(row['resource_score']),2)
            for key in ('target_probability','positive_votes','panel_size','band','reference_game_score'):
                target.loc[sid,key]=row[key]
            handle.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    frame.to_csv(output/'features.csv',index=False)
    target.reset_index().to_csv(output/'targets.csv',index=False)
    (output/'policy.json').write_bytes(author.json_bytes(PANEL_POLICY))
    artifacts={name:file_hash(output/name) for name in old['artifact_hashes']}
    sources=['scripts/aml_attribute_label_policy.py','scripts/relabel_aml_attribute_dataset.py',
             'src/aml_workshop_simulator/services/aml_game_attribute_features_v1.py']
    report=dict(rows=len(rows),bands=dict(Counter(target.band)),changed_targets=int(changed),
                source_dataset_sha256=file_hash(source/'audit.json'), source_replay_sha256=file_hash(source/'readback-audit.json'),
                context_sha256=old['context_sha256'],source_policy_sha256=author.digest(PANEL_POLICY),
                artifact_hashes=artifacts,source_hashes={name:file_hash(name) for name in sources},
                groups_preserved=True,split_counts=dict(Counter(target.split)),release_ready=False)
    (output/'audit.json').write_bytes(author.json_bytes(report))
    # No steps/config changed: inherited financial replay is bound by source hashes.
    # All canonical steps were separately validated and new features read back below.
    read=pd.read_csv(output/'features.csv',float_precision='round_trip')
    require(np.array_equal(read.drop(columns='scenario_id').to_numpy(),frame.drop(columns='scenario_id').to_numpy()),'Feature readback mismatch')
    (output/'readback-audit.json').write_bytes(author.json_bytes(dict(passed=True,rows=len(rows),
        source_financial_replay_sha256=file_hash(source/'readback-audit.json'),
        source_artifacts=old['artifact_hashes'],canonical_validation=not reuse_canonical,
        canonical_validation_inherited=reuse_canonical,identical_steps_and_context=True,
        feature_readback_exact=True,group_splits_preserved=True,audit_script_sha256=file_hash(__file__))))
    print(json.dumps({k:v for k,v in report.items() if k not in ('artifact_hashes','source_hashes')},default=int),flush=True)


def finalize(source, output):
    """Verify every serialized row before resuming interrupted manifest writing."""
    old=json.loads((source/'audit.json').read_bytes())
    replay=json.loads((source/'readback-audit.json').read_bytes())
    require(replay['passed'] and replay['rows']==old['rows'],'Source replay failed')
    for name,digest in old['artifact_hashes'].items():
        require(file_hash(source/name)==digest,'Source drift')
    for name in ('context.json','groups.json'):
        require(file_hash(source/name)==file_hash(output/name),'Context/group drift')
    frame=pd.read_csv(output/'features.csv',float_precision='round_trip').set_index('scenario_id')
    target=pd.read_csv(output/'targets.csv',float_precision='round_trip').set_index('scenario_id')
    original=pd.read_csv(source/'targets.csv',float_precision='round_trip').set_index('scenario_id')
    require(target[['group_id','split']].equals(original[['group_id','split']]),'Split drift')
    count=0
    from itertools import zip_longest
    with (source/'casebook.jsonl').open(encoding='utf8') as a,(output/'casebook.jsonl').open(encoding='utf8') as b:
        for left,right in zip_longest(a,b):
            require(left is not None and right is not None,'Row count mismatch')
            before,after=json.loads(left),json.loads(right)
            require(before['scenario_id']==after['scenario_id'] and before['steps']==after['steps'],'Step drift')
            sid=after['scenario_id']
            actual=extract_panel_features(after['steps'])
            require(all(float(frame.loc[sid,k])==v for k,v in actual.items()),'Feature readback mismatch')
            require(after['target_probability']==target.loc[sid,'target_probability'],'Casebook label mismatch')
            count+=1
    require(count==old['rows'],'Incomplete rows')
    for start in range(0,count,2000):
        batch=frame.iloc[start:start+2000]
        expected=interpretation_targets(views(batch)).reshape(3,len(batch)).mean(axis=0)
        require(np.allclose(expected,target.loc[batch.index,'target_probability'],atol=1e-12,rtol=0),'Label readback mismatch')
    sources=['scripts/aml_attribute_label_policy.py','scripts/relabel_aml_attribute_dataset.py',
             'src/aml_workshop_simulator/services/aml_game_attribute_features_v1.py']
    report=dict(rows=count,bands=dict(Counter(target.band)),changed_targets=int((abs(target.target_probability-original.target_probability)>1e-12).sum()),
        source_dataset_sha256=file_hash(source/'audit.json'),source_replay_sha256=file_hash(source/'readback-audit.json'),
        context_sha256=old['context_sha256'],source_policy_sha256=author.digest(PANEL_POLICY),
        artifact_hashes={name:file_hash(output/name) for name in old['artifact_hashes']},
        source_hashes={name:file_hash(name) for name in sources},groups_preserved=True,
        split_counts=dict(Counter(target.split)),release_ready=False)
    (output/'audit.json').write_bytes(author.json_bytes(report))
    (output/'readback-audit.json').write_bytes(author.json_bytes(dict(passed=True,rows=count,
        source_financial_replay_sha256=file_hash(source/'readback-audit.json'),source_artifacts=old['artifact_hashes'],
        identical_steps_and_context=True,feature_readback_exact=True,label_readback_exact=True,
        group_splits_preserved=True,audit_script_sha256=file_hash(__file__))))
    print(json.dumps(dict(rows=count,bands=report['bands'],changed_targets=report['changed_targets'])),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--finalize',action='store_true')
    p.add_argument('--reuse-canonical',action='store_true')
    a=p.parse_args()
    if a.finalize:
        finalize(a.source,a.output)
    else:
        build(a.source,a.output,a.reuse_canonical)
