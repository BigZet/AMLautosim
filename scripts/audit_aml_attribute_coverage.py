"""Audit selectable values and conditional combinations in each dataset split."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes
from src.aml_workshop_simulator.services.semantic_contract import INCOMING_KINDS, BANK_COUNTRIES, allowed_party, fields_for


def expected(config):
    required = set()
    def add(*parts):
        required.add('|'.join(map(str, parts)))
    for card in config['card_snapshots']:
        code = card['code']
        for field in fields_for(code):
            if field['key'] not in {'incoming_kind', 'bank_country', 'income_basis'}:
                raise ValueError('Uncovered editor field: '+code+'.'+field['key'])
        for channel in card['channels']:
            add(code, 'channel', channel)
        for wait in config['behavior']['timeline']['waiting_costs']:
            add(code, 'wait', wait)
        kinds = tuple(INCOMING_KINDS) if code == 'incoming_transfer' else (None,)
        for kind in kinds:
            details = {'incoming_kind': kind} if kind else {}
            scope = code + (':' + kind if kind else '')
            if kind:
                add(code, 'incoming_kind', kind)
            if kind == 'bank_transfer':
                for country in BANK_COUNTRIES:
                    add(scope, 'bank_country', country)
            for purpose in allowed_purposes({'card': {'code': code}, 'action_details': details}):
                add(scope, 'purpose', purpose)
            for party in config['behavior']['counterparties']:
                if allowed_party(code, party, details):
                    add(scope, 'party', party['id'])
        if code == 'salary':
            add(code, 'income_basis', 'payroll_registry')
    return required


def audit(dataset, output):
    config = json.loads((dataset / 'context.json').read_bytes())
    cards = {c['code']: c for c in config['card_snapshots']}
    targets = {r['scenario_id']: r['split'] for r in csv.DictReader((dataset / 'targets.csv').open(encoding='utf8'))}
    groups = json.loads((dataset / 'groups.json').read_bytes())['scenario_groups']
    related_variants = 0
    counts = defaultdict(Counter)
    rows = Counter()
    explicit = Counter()
    for line in (dataset / 'casebook.jsonl').open(encoding='utf8'):
        row = json.loads(line)
        split = targets[row['scenario_id']]
        if row.get('source_scenario_id'):
            parent = row['source_scenario_id']
            if targets[parent] != split or groups[parent] != groups[row['scenario_id']]:
                raise ValueError('Related variant separated from parent: '+row['scenario_id'])
            related_variants += 1
        rows[split] += 1
        for index, step in enumerate(row['steps']):
            code = step['card']['code']
            details = step.get('action_details', {})
            kind = details.get('incoming_kind')
            scope = code + (':' + kind if kind else '')
            observations = [(scope, 'purpose', step['purpose_code'])]
            if cards[code]['channels']:
                channel = step.get('context', {}).get('channel', cards[code]['channels'][0])
                observations.append((code, 'channel', channel))
                if 'channel' in step.get('context', {}):
                    explicit[code] += 1
            if index:
                observations.append((code, 'wait', step['interval_minutes']))
            if kind:
                observations.append((code, 'incoming_kind', kind))
            if 'bank_country' in details:
                observations.append((scope, 'bank_country', details['bank_country']))
            if 'income_basis' in details:
                observations.append((code, 'income_basis', details['income_basis']))
            party = step.get('sender_id') or step.get('recipient_id')
            if party:
                observations.append((scope, 'party', party))
            for parts in observations:
                key = '|'.join(map(str, parts))
                counts[split][key] += 1
                counts['all'][key] += 1
    required = expected(config)
    missing = {split: sorted(required - set(values)) for split, values in counts.items()}
    selectable_facts = [f['id'] for f in config['behavior']['aml_context']['facts'] if f['fact_type'] != 'opening_balance']
    report = dict(rows=dict(rows), required_values=len(required), related_variants_checked=related_variants,
                  counts={k: dict(v) for k,v in counts.items()},
                  missing=missing, explicit_channels=dict(explicit), selectable_claims=selectable_facts,
                  passed=not any(missing.values()) and not selectable_facts,
                  scope='Every selectable value per operation and split; incoming kind x purpose/party/country. Not exhaustive Cartesian combinations.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:report[k] for k in ('rows','required_values','missing','passed')}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-pass', action='store_true')
    args = parser.parse_args()
    result = audit(args.dataset,args.output)
    if args.require_pass and not result['passed']:
        raise SystemExit('Attribute coverage incomplete')
