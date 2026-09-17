"""Read-only audit; run from the repository root. No database or dataset writes."""
import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.aml_workshop_simulator.services.aml_context import canonical_steps, evaluate
from src.aml_workshop_simulator.services.game_classifier import get_game_classifier

DATA = Path('E:/AMLautosim-artifacts/aml-probability-v1/game-curriculum-v6r1-final')
OUT = Path(__file__).with_name('operation-purpose-audit-2026-09-17.json')


def main():
    config = json.loads((DATA / 'context.json').read_text(encoding='utf-8'))
    parties = {p['id']: p for p in config['behavior']['counterparties']}
    purposes = [p['code'] for p in config['behavior']['aml_context']['purpose_catalog']]
    counts, suspicious, examples, representatives = Counter(), Counter(), {}, {}
    rows = steps_count = claims = 0
    ids = set()
    digest = hashlib.sha256()
    with (DATA / 'casebook.jsonl').open('rb') as stream:
        for raw in stream:
            digest.update(raw)
            row = json.loads(raw)
            rows += 1
            ids.add(row['scenario_id'])
            flags = set()
            for index, step in enumerate(row['steps'], 1):
                steps_count += 1
                code, purpose = step['card']['code'], step.get('purpose_code')
                counts[(code, purpose)] += 1
                claims += step.get('claim_id') is not None
                representatives.setdefault(code, (row, index - 1))
                party_id = step.get('sender_id') or step.get('recipient_id')
                party = parties.get(party_id, {})
                # Ambiguity indicator, NOT an invalidity or fraud label.
                if purpose == 'shared_expense' and party.get('personal_relationship') == 'unknown':
                    suspicious['shared_expense_unknown_relationship_steps'] += 1
                    flags.add('shared_expense_unknown_relationship_chains')
                    examples.setdefault('shared_expense_unknown_relationship', dict(
                        scenario_id=row['scenario_id'], step_number=index, step=step, party=party))
            suspicious.update(flags)
    model = get_game_classifier()
    probes = []
    for code, (row, index) in representatives.items():
        base = model.predict(row['steps'], config, explain=False, require_pin=False)
        for purpose in purposes:
            steps = deepcopy(row['steps'])
            original = steps[index]['purpose_code']
            steps[index]['purpose_code'] = purpose
            record = dict(operation=code, scenario_id=row['scenario_id'], step_number=index+1,
                          original_purpose=original, changed_purpose=purpose, original_probability=base)
            try:
                canonical_steps(steps, config)
                resources = evaluate(steps, config)
                p = model.predict(steps, config, explain=False, require_pin=False)
                record.update(accepted=True, probability=p, difference=p-base,
                              evaluation_equal=resources == evaluate(row['steps'], config))
            except Exception as exc:
                record.update(accepted=False, error=str(exc))
            probes.append(record)
    attribute_probes = []
    row, index = representatives['incoming_transfer']
    for name, details, sender, purpose in [
        ('crypto_p2p_salary', {'incoming_kind':'crypto_p2p'}, 'A', 'salary'),
        ('exchange_shared_expense', {'incoming_kind':'exchange_withdrawal'}, 'exchange', 'shared_expense'),
        ('exchange_salary', {'incoming_kind':'exchange_withdrawal'}, 'exchange', 'salary'),
        ('invalid_bank_country_on_p2p', {'incoming_kind':'crypto_p2p','bank_country':'RU'}, 'A', 'asset_sale'),
        ('invalid_exchange_sender', {'incoming_kind':'exchange_withdrawal'}, 'A', 'asset_sale'),
    ]:
        steps = deepcopy(row['steps'])
        steps[index].update(action_details=details, sender_id=sender, purpose_code=purpose)
        record = dict(name=name, scenario_id=row['scenario_id'], step_number=index+1,
                      action_details=details, sender_id=sender, purpose_code=purpose)
        try:
            canonical_steps(steps, config)
            evaluate(steps, config)
            record.update(accepted=True, probability=model.predict(steps, config, explain=False, require_pin=False))
        except Exception as exc:
            record.update(accepted=False, error=str(exc))
        attribute_probes.append(record)
    result = dict(dataset=str(DATA), casebook_sha256=digest.hexdigest(), chains=rows,
                  unique_scenario_ids=len(ids), operations=steps_count, nonnull_claim_steps=claims,
                  purpose_catalog=purposes, model_identity=model.model_identity,
                  operation_purpose_counts=[dict(operation=k[0], purpose=k[1], count=v)
                                            for k,v in sorted(counts.items())],
                  ambiguity_indicators=dict(suspicious), examples=examples, probes=probes,
                  attribute_probes=attribute_probes)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('probes','examples','model_identity')}, ensure_ascii=False))
    print('probes', len(probes), 'accepted', sum(p['accepted'] for p in probes),
          'changed_probability', sum(p.get('difference', 0) != 0 for p in probes))


if __name__ == '__main__':
    main()
