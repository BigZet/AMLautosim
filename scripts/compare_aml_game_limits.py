"""Measure new playable chains and expanded-limit coverage against a frozen release."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from src.aml_workshop_simulator.core.errors import ValidationFailed


def compare(dataset, baseline, output):
    old = json.loads(baseline.read_bytes())
    new = json.loads((dataset/'context.json').read_bytes())
    assert old['behavior'] == new['behavior'], 'Shared history/context changed'
    limits = {card['code']: dict(card) for card in old['card_snapshots']}
    for operation in old['operations']:
        limits[operation['code']].update({k:v for k,v in operation.items() if v is not None})
    counts, bands, purposes = Counter(), Counter(), Counter()
    examples = {}
    with (dataset/'casebook.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            steps = row['steps']
            kinds = Counter(s['card']['code'] for s in steps)
            cash = sum(Decimal(s['amount']) for s in steps if s['card']['code']=='cash_withdrawal')
            flags = {
                'four_receipts': kinds['incoming_transfer'] > 3,
                'over_eight_card_transfers': kinds['card_transfer'] > 8,
                'over_fourteen_actions': len(steps) > 14,
                'incoming_over_80000': any(s['card']['code']=='incoming_transfer' and Decimal(s['amount'])>80000 for s in steps),
                'card_over_80000': any(s['card']['code']=='card_transfer' and Decimal(s['amount'])>80000 for s in steps),
                'cash_operation_over_100000': any(s['card']['code']=='cash_withdrawal' and Decimal(s['amount'])>100000 for s in steps),
                'total_cash_over_120000': cash > 120000,
            }
            directly_exceeds = (
                len(steps) > old['objectives']['max_actions']
                or cash > Decimal(old['constraints']['category_limits']['cash'])
                or any(n > limits[code]['max_occurrences'] for code,n in kinds.items())
                or any(Decimal(s['amount']) > Decimal(limits[s['card']['code']]['max_amount']) for s in steps)
            )
            if directly_exceeds:
                blockers = [{'reason':'baseline_limit_exceeded'}]
            else:
                try:
                    blockers = submit_blockers(evaluate(steps, old))
                except ValidationFailed as exc:
                    blockers = [{'reason': 'old_contract_rejection', 'message': str(exc)}]
            flags['newly_playable'] = bool(blockers)
            counts['chains'] += 1
            for key, value in flags.items():
                counts[key] += value
                if value:
                    examples.setdefault(key, row['scenario_id'])
            if blockers:
                bands[row['band']] += 1
            purposes.update(s['purpose_code'] for s in steps)
    result = dict(counts=dict(counts), newly_playable_bands=dict(bands), examples=examples,
                  purpose_counts=dict(purposes), immutable_behavior=True,
                  source=str(dataset), baseline=str(baseline))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('--baseline',type=Path,default=Path('resources/catboost_models/aml-game-v1/context.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    compare(args.dataset,args.baseline,args.output)
