"""CI must not hide unclassified tests, collection failures or new regressions."""

import pytest


def test_missing_and_conflicting_test_classifications_fail_closed():
    from scripts.ci_test_policy import classify

    with pytest.raises(ValueError, match='Unclassified'):
        classify('tests/unit/new.py', set(), {})
    with pytest.raises(ValueError, match='Conflicting'):
        classify('tests/unit/new.py', {'runtime', 'research'}, {})
    assert classify('tests/unit/new.py', {'runtime'}, {}) == 'runtime'
    assert classify('tests/unit/known.py', set(), {'tests/unit/known.py': 'research'}) == 'research'


def test_research_baseline_reports_known_debt_and_rejects_new_failures():
    from scripts.ci_test_policy import check_research

    baseline = {'failures': {'known': 'documented baseline'}}
    report = {'exit_code': 1, 'collected': ['known', 'new'], 'failures': {'known': 'failure'}}
    assert check_research(report, baseline) == {'known_failures': ['known'], 'resolved': []}
    report['failures']['new'] = 'regression'
    with pytest.raises(ValueError, match='new'):
        check_research(report, baseline)
    report.update(exit_code=2, failures={})
    with pytest.raises(ValueError, match='collection|interrupted'):
        check_research(report, baseline)


def test_removed_research_cases_are_not_reported_as_fixed():
    from scripts.ci_test_policy import check_research

    with pytest.raises(ValueError, match='disappeared'):
        check_research({'exit_code': 0, 'collected': [], 'failures': {}}, {'failures': {'missing': 'debt'}})


def test_runtime_inventory_detects_disappearing_tests():
    from scripts.ci_test_policy import check_inventory

    check_inventory({'collected': ['a', 'b', 'new']}, ['a', 'b'])
    with pytest.raises(ValueError, match='b'):
        check_inventory({'collected': ['a']}, ['a', 'b'])
