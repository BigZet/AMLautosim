"""Inspect actual CatBoost inputs and controlled changes of accepted API steps."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import pandas as pd

from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
from src.aml_workshop_simulator.services.aml_context import canonical_steps
from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes


def run(output=None):
    model = get_game_classifier()
    config = deepcopy(model.context)
    config['risk_model'] = model.identity
    examples = json.loads(Path('tests/fixtures/attribute_classifier_examples.json').read_bytes())
    def frame(steps):
        return model.views(pd.DataFrame([model.extract(canonical_steps(steps,config))]))[model.features]
    results = defaultdict(lambda: dict(comparisons=0, changed_inputs=0, changed_predictions=0, max_probability_difference=0.0))
    evidence = []
    for row in examples:
        original = row['steps']
        baseline = frame(original)
        probability = model.predict(original, config, explain=False)
        changes = {}
        for i,step in enumerate(original):
            code = step['card']['code']
            options = []
            if code == 'card_transfer':
                options.append(('channel', 'context', 'channel', 'web' if step.get('context',{}).get('channel') != 'web' else 'branch'))
                options.append(('recipient_identity', None, 'recipient_id', 'B' if step['recipient_id']=='A' else 'A'))
            if code == 'incoming_transfer' and step['action_details']['incoming_kind']=='bank_transfer':
                options.append(('bank_country','action_details','bank_country','KG' if step['action_details']['bank_country']=='RU' else 'RU'))
                changed=deepcopy(original)
                changed[i]['action_details']={'incoming_kind':'payment_service'}
                changes.setdefault('incoming_kind_same_sender',changed)
            purposes = [v for v in allowed_purposes(step) if v != step['purpose_code']]
            if purposes:
                options.append(('purpose_code',None,'purpose_code',purposes[0]))
            if i:
                options.append(('interval_minutes',None,'interval_minutes',1440 if step['interval_minutes']!=1440 else 1))
            for name,namespace,key,value in options:
                if name in changes:
                    continue
                changed=deepcopy(original)
                target=changed[i].setdefault(namespace,{}) if namespace else changed[i]
                target[key]=value
                changes[name]=changed
        for name,changed in changes.items():
            value=model.predict(changed,config,explain=False)
            same=baseline.equals(frame(changed))
            item=results[name]
            item['comparisons']+=1
            item['changed_inputs']+=not same
            item['changed_predictions']+=value!=probability
            item['max_probability_difference']=max(item['max_probability_difference'],abs(value-probability))
            evidence.append(dict(scenario_id=row['scenario_id'],attribute=name,same_inputs=same,before=probability,after=value))
    report=dict(model=model.identity,features=model.model.feature_names_,categorical_feature_indices=model.model.get_cat_feature_indices(),
                results=dict(results),evidence=evidence,
                scope='Canonical valid steps; this test isolates classifier prediction, not resource feasibility or leaderboard score')
    path=output or Path('docs/verification/aml-classifier-v1/attribute-model-usage.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'features':report['features'],'categorical_feature_indices':report['categorical_feature_indices'],'results':report['results']},ensure_ascii=False))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    run(parser.parse_args().output)
