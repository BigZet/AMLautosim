"""Choose held-out examples covering each incoming source and payment channel."""
import argparse
import csv
import json
from pathlib import Path


def flags(row):
    result = set()
    for index, step in enumerate(row['steps']):
        code = step['card']['code']
        kind = step.get('action_details', {}).get('incoming_kind')
        scope = code + (':' + kind if kind else '')
        result.add((scope, 'purpose', step['purpose_code']))
        if index:
            result.add((code, 'wait', step['interval_minutes']))
        party = step.get('sender_id') or step.get('recipient_id')
        if party:
            result.add((scope, 'party', party))
        for key, value in step.get('action_details', {}).items():
            result.add((scope if key == 'bank_country' else code, key, value))
        if 'channel' in step.get('context', {}):
            result.add((code, 'channel', step['context']['channel']))
    return result


def select(dataset, model, output):
    predictions = {r['scenario_id']: float(r['probability']) for r in csv.DictReader((model/'predictions.csv').open()) if r['split']=='test'}
    rows = []
    for line in (dataset/'casebook.jsonl').open(encoding='utf8'):
        row = json.loads(line)
        if row['scenario_id'] in predictions:
            row['probability'] = predictions[row['scenario_id']]
            rows.append(row)
    selected, covered, families = [], set(), set()
    for band, count in [('low',10),('high',10),('grey',5)]:
        pool = [r for r in rows if ('low' if r['probability']<.1 else 'high' if r['probability']>=.9 else 'grey')==band]
        for _ in range(count):
            row = max(pool,key=lambda r:(len(flags(r)-covered),r['route_family'] not in families))
            pool.remove(row)
            covered.update(flags(row))
            families.add(row['route_family'])
            selected.append({k:row[k] for k in ('scenario_id','steps','probability','target_probability','route_family')})
    required = set().union(*(flags(r) for r in rows))
    if required - covered:
        raise ValueError('Published examples miss attributes: '+str(required-covered))
    output.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Selected 25 held-out examples; attribute values covered:',len(covered))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset',type=Path)
    p.add_argument('model',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    select(a.dataset,a.model,a.output)
