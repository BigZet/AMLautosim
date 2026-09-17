"""Exercise only the named, disposable Docker audit stack; omit credentials."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts.check_expanded_balance import demo_steps  # noqa: E402


def main():
    cfg = dotenv_values(ROOT / '.local-run/audit-docker.env')
    docker_bin = Path(os.environ['LOCALAPPDATA']) / 'Programs/DockerDesktop/resources/bin'
    env = dict(os.environ, PATH=str(docker_bin) + os.pathsep + os.environ['PATH'])
    compose = [str(docker_bin / 'docker.exe'), 'compose', '--project-name',
               'aml-audit-20260916', '--env-file', '.local-run/audit-docker.env']
    report = {'api_port': 58400, 'ui_port': 58480, 'requests': []}

    def command(args, **kwargs):
        r = subprocess.run(compose + args, cwd=ROOT, env=env, capture_output=True,
                           timeout=180, **kwargs)
        if r.returncode:
            raise RuntimeError(f'Compose command failed: {args[:4]}, exit {r.returncode}')
        return r.stdout

    with httpx.Client(base_url='http://127.0.0.1:58400/api/v1', timeout=60) as client:
        def request(method, path, token=None, body=None, status=200):
            headers = {'X-Session-ID': token} if token else {}
            r = client.request(method, path, headers=headers, json=body)
            report['requests'].append({'method': method, 'path': path, 'status': r.status_code})
            assert r.status_code == status, (path, r.status_code, r.text)
            return r.json() if r.content else None

        admin = request('POST', '/auth/login', body={'email': cfg['BOOTSTRAP_ADMIN_EMAIL'],
                        'password': cfg['BOOTSTRAP_ADMIN_PASSWORD'], 'audience': 'admin'})['session_id']
        current = request('GET', '/admin/rounds/current', admin)
        assert current['status'] == 'draft', 'This script requires a fresh audit stack'
        rid = current['id']
        request('POST', f'/admin/rounds/{rid}/start', admin)
        # Synthetic credentials, only in this fresh loopback audit stack.
        password = 'Audit2026_LocalOnly!'
        email = 'audit-browser@example.com'
        request('POST', '/auth/register', body={'email': email, 'password': password,
                'display_name': 'Контейнерный аудит'}, status=201)
        player = request('POST', '/auth/login', body={'email': email, 'password': password})['session_id']
        steps = demo_steps(current['game_config'])
        preview = request('POST', f'/rounds/{rid}/scenario/preview', player, {'steps': steps})
        assert preview['can_submit'] and 'risk_score' not in str(preview)
        saved = request('PUT', f'/rounds/{rid}/scenario', player,
                        {'steps': steps, 'expected_revision': 0, 'client_mutation_id': str(uuid4())})
        submission = {'steps': steps, 'expected_revision': saved['revision'], 'client_mutation_id': str(uuid4())}
        request('POST', f'/rounds/{rid}/scenario/submit', player, submission)
        assert request('GET', '/rounds/current/state', player)['result'] is None
        scoring = request('POST', f'/admin/rounds/{rid}/score', admin)
        assert scoring['scored_count'] == 1
        before = request('GET', '/rounds/current/state', player)
        explanation = before['result']['explanation']
        assert explanation['method'] == 'catboost-tree-shap' and len(explanation['factors']) == 84
        assert explanation['additivity_error'] < 1e-6
        request('GET', f'/rounds/{rid}/leaderboard', player)
        assert request('POST', f'/admin/rounds/{rid}/score', admin)['scored_count'] == 1
        request('POST', f'/rounds/{rid}/scenario/submit', player, submission)
        command(['restart', 'api', 'ui'])
        deadline = time.monotonic() + 120
        while True:
            try:
                ready = httpx.get('http://127.0.0.1:58400/health/ready', timeout=5)
                if ready.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('API did not recover after restart')
            time.sleep(1)
        request('GET', '/auth/session', player)
        after = request('GET', '/rounds/current/state', player)
        assert before['result'] == after['result'] and before['scenario'] == after['scenario']
        report.update(gameplay_passed=True, restart_preserves_session_and_results=True,
                      round_id=rid, risk_score=explanation['normalized_score'],
                      explanation_factors=len(explanation['factors']),
                      shap_additivity_error=explanation['additivity_error'])

    query = """SELECT json_build_object(
      'users',(SELECT count(*) FROM users), 'sessions',(SELECT count(*) FROM sessions),
      'rounds',(SELECT count(*) FROM rounds), 'scenarios',(SELECT count(*) FROM scenarios),
      'scoring_results',(SELECT count(*) FROM scoring_results), 'audit_events',(SELECT count(*) FROM audit_events),
      'scenario_hash',(SELECT md5(string_agg(steps::text,'' ORDER BY id)) FROM scenarios),
      'explanation_hash',(SELECT md5(string_agg(explanation::text,'' ORDER BY id)) FROM scoring_results));"""
    def snapshot(db):
        return json.loads(command(['exec', '-T', 'db', 'psql', '-U', 'aml_audit', '-d', db, '-Atc', query]))
    original = snapshot('aml_audit')
    archive = command(['exec', '-T', 'db', 'pg_dump', '-U', 'aml_audit', '-d', 'aml_audit', '-Fc'])
    restore_name = 'aml_audit_restore_' + uuid4().hex
    command(['exec', '-T', 'db', 'createdb', '-U', 'aml_audit', restore_name])
    try:
        command(['exec', '-T', 'db', 'pg_restore', '-U', 'aml_audit', '--no-owner', '--no-privileges',
                 '-d', restore_name], input=archive)
        assert original == snapshot(restore_name)
    finally:
        command(['exec', '-T', 'db', 'dropdb', '-U', 'aml_audit', restore_name])
    report.update(backup_restore_passed=True, restored_counts_and_hashes=original,
                  dump_sha256=hashlib.sha256(archive).hexdigest(), dump_bytes=len(archive))
    report['runtime_uid'] = command(['exec', '-T', 'api', 'id', '-u']).decode().strip()
    assert report['runtime_uid'] == '10001'
    report['linux_pip_check'] = command(['exec', '-T', 'api', 'python', '-m', 'pip', 'check']).decode().strip()
    report['passed'] = True
    (OUT / 'docker-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
