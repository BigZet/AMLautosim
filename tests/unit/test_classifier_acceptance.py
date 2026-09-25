from copy import deepcopy
from src.aml_workshop_simulator.services.classifier_acceptance import gameplay_accepted



def test_exception_is_bound_to_reviewed_report_and_only_grey_error():
    case = {"probability": .6, "target": .3}
    report = {"passed": False, "failures": ["individual_probability_error_above_0.25"],
              "largest_errors": [case], "max_target_error": .3}
    digest = "test-report-sha256"
    exception = {"approval": "explicit_user_approval", "report_sha256": digest,
                 "reviewed_case": case, "approved_max_error": .3}
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
