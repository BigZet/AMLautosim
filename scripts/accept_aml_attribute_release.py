"""Accept only a replayed, tested model with complete selectable-attribute coverage."""
import argparse
import json
from pathlib import Path

from scripts.accept_aml_relaxed_release import accept
from scripts.audit_aml_attribute_coverage import audit
from scripts.audit_aml_history_population import file_hash, require


def run(dataset, model, comparison, coverage, accept_reviewed_grey_error=False):
    report = audit(dataset, coverage)
    require(report['passed'], 'Selectable attribute coverage incomplete')
    exception = None
    if accept_reviewed_grey_error:
        gameplay = json.loads((model/'gameplay-audit.json').read_bytes())
        require(gameplay['largest_errors'][0]['seed'] == 2061901495, 'Not the reviewed scenario')
        require(gameplay['max_target_error'] == 0.2818515694045168, 'Not the reviewed error')
        exception = dict(approval='explicit_user_approval', user_statement='Это допустимо',
                         approved_on='2026-09-17', report_sha256=file_hash(model/'gameplay-audit.json'),
                         reviewed_case=gameplay['largest_errors'][0], approved_max_error=gameplay['max_target_error'])
    accept(dataset, model, comparison, exception)
    path = dataset / 'acceptance.json'
    acceptance = json.loads(path.read_bytes())
    acceptance.update(attribute_coverage_sha256=file_hash(coverage),
                      attribute_coverage=report,
                      attribute_coverage_required=report['required_values'],
                      attribute_coverage_passed=True,
                      attribute_coverage_auditor_sha256=file_hash('scripts/audit_aml_attribute_coverage.py'))
    path.write_text(json.dumps(acceptance,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset', type=Path)
    p.add_argument('model', type=Path)
    p.add_argument('--comparison', type=Path, required=True)
    p.add_argument('--coverage', type=Path, required=True)
    p.add_argument('--accept-reviewed-grey-error', action='store_true')
    args = p.parse_args()
    run(args.dataset,args.model,args.comparison,args.coverage,args.accept_reviewed_grey_error)
