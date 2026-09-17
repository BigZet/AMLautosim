from copy import deepcopy
import json
from src.aml_workshop_simulator.services.classifier_acceptance import gameplay_accepted
from src.aml_workshop_simulator.services.game_classifier import ROOT, file_hash

DEFAULT_PACKAGE = ROOT / 'resources/catboost_models/aml-game-attributes-v1'


def test_exception_is_bound_to_reviewed_report_and_only_grey_error():
    report=json.loads((DEFAULT_PACKAGE/'gameplay-audit.json').read_bytes())
    exception=json.loads((DEFAULT_PACKAGE/'acceptance.json').read_bytes())['gameplay_exception']
    digest=file_hash(DEFAULT_PACKAGE/'gameplay-audit.json')
    assert not gameplay_accepted(report,digest)
    assert gameplay_accepted(report,digest,exception)
    assert not gameplay_accepted(report,'changed-report',exception)
    changed=deepcopy(report)
    changed['failures'].append('other_failure')
    assert not gameplay_accepted(changed,digest,exception)
    changed=deepcopy(report)
    changed['max_target_error'] += .001
    assert not gameplay_accepted(changed,digest,exception)
    changed=deepcopy(report)
    changed['largest_errors'][0]['probability']=.95
    changed_exception={**exception,'reviewed_case':changed['largest_errors'][0]}
    assert not gameplay_accepted(changed,digest,changed_exception)
