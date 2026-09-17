"""Validate quality evidence, including an explicitly approved report-bound exception."""


def gameplay_accepted(report, report_sha256, exception=None):
    if report.get('passed') and not report.get('failures'):
        policy = report.get('error_tolerance_policy')
        if policy is not None:
            cases = report.get('above_tolerance_cases', [])
            return (
                policy.get('approval') == 'explicit_user_instruction'
                and policy.get('absolute_probability_error') == .25
                and policy.get('maximum_chains_above_tolerance') == 20
                and policy.get('actual_chains_above_tolerance') == len(cases)
                and len(cases) <= 20
                and report.get('seed_count') == 5000
                and report.get('counts', {}).get('valid', 0) >= 1500
                and all(abs(c['probability']-c['target']) > .25 for c in cases)
            )
        return True
    if not exception or exception.get('approval') != 'explicit_user_approval':
        return False
    if exception.get('report_sha256') != report_sha256:
        return False
    if report.get('failures') != ['individual_probability_error_above_0.25']:
        return False
    errors = report.get('largest_errors', [])
    if not errors or errors[0] != exception.get('reviewed_case'):
        return False
    if report.get('max_target_error') != exception.get('approved_max_error'):
        return False
    return all(
        .1 <= case['probability'] < .9 and .1 <= case['target'] < .9
        for case in errors if abs(case['probability'] - case['target']) > .25
    )
