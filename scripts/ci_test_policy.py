"""Explicit test ownership, machine-readable runs and fail-closed CI baselines."""

import argparse
import json
from pathlib import Path

import pytest

KINDS = {'runtime', 'research', 'load', 'browser'}
ROOT = Path(__file__).resolve().parents[1]
STATE = pytest.StashKey[dict]()


def classify(path: str, explicit: set[str], suites: dict[str, str]) -> str:
    if len(explicit) > 1:
        raise ValueError(f'Conflicting test classifications: {path}: {sorted(explicit)}')
    kind = next(iter(explicit), suites.get(path))
    if kind not in KINDS:
        raise ValueError(f'Unclassified test: {path}; declare one suite explicitly')
    return kind


def check_inventory(report: dict, expected: list[str]) -> None:
    missing = sorted(set(expected) - set(report['collected']))
    if missing:
        raise ValueError('Runtime tests disappeared: ' + ', '.join(missing))


def check_research(report: dict, baseline: dict) -> dict:
    if report['exit_code'] not in (0, 1):
        raise ValueError('Research collection failed or run was interrupted')
    known = set(baseline['failures'])
    missing = known - set(report['collected'])
    if missing:
        raise ValueError('Research cases disappeared: ' + ', '.join(sorted(missing)))
    skipped = known & set(report.get('skipped', []))
    if skipped:
        raise ValueError('Known research failures were skipped: ' + ', '.join(sorted(skipped)))
    failures = set(report['failures'])
    new = failures - known
    if new:
        raise ValueError('New research failures: ' + ', '.join(sorted(new)))
    if report['exit_code'] == 1 and not failures:
        raise ValueError('Research failed without recorded test failures')
    return {'known_failures': sorted(failures & known), 'resolved': sorted(known - failures)}


def pytest_addoption(parser):
    parser.addoption('--suite-report', help='Write collected node IDs and outcomes as JSON')


def pytest_configure(config):
    config.stash[STATE] = {'collected': [], 'failures': {}, 'skipped': []}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    suites = json.loads((ROOT / 'tests/suites.json').read_bytes())['modules']
    missing = [name for name in suites if not (ROOT / name).is_file()]
    if missing:
        raise pytest.UsageError('Classified test modules disappeared: ' + ', '.join(missing))
    for item in items:
        path = item.path.relative_to(ROOT).as_posix()
        explicit = {m.name for m in item.iter_markers() if m.name in KINDS}
        try:
            kind = classify(path, explicit, suites)
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        if not explicit:
            item.add_marker(getattr(pytest.mark, kind))


def pytest_collection_finish(session):
    session.config.stash[STATE]['collected'] = [item.nodeid for item in session.items]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    state = item.config.stash[STATE]
    if report.failed:
        crash = getattr(report.longrepr, 'reprcrash', None)
        reason = crash.message if crash else str(report.longrepr)[-800:]
        state['failures'][report.nodeid] = f'{report.when}: {reason}'
    elif report.skipped:
        state['skipped'].append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    destination = session.config.getoption('--suite-report')
    if destination:
        report = {**session.config.stash[STATE], 'exit_code': int(exitstatus)}
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('research', 'runtime'))
    parser.add_argument('report', type=Path)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--group', choices=('unit', 'api'))
    args = parser.parse_args()
    report = json.loads(args.report.read_bytes())
    baseline = json.loads(args.baseline.read_bytes())
    if args.kind == 'research':
        print(json.dumps(check_research(report, baseline), indent=2))
    else:
        check_inventory(report, baseline[args.group])
        print('Runtime inventory preserved')


if __name__ == '__main__':
    main()
