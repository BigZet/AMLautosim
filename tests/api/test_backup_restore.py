"""Online backup drill using the test-owned PostgreSQL container only."""

import json
import os
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from scripts.ops.backup_database import backup, pg_command
from scripts.ops.restore_database import restore


@pytest.mark.parametrize('phase', ['draft', 'scored'])
def test_online_backup_and_restore(phase, request_api, admin, player, active_round, chain, command, sql, tmp_path, monkeypatch):
    # CI may use native PostgreSQL tools; local Windows uses only this explicit container.
    container = os.environ.get('TEST_PG_CONTAINER')
    url = make_url(os.environ['DATABASE_URL'])
    for name, value in {'PGHOST': '127.0.0.1' if container else url.host,
                        'PGPORT': '5432' if container else str(url.port),
                        'PGUSER': url.username, 'PGPASSWORD': url.password, 'PGDATABASE': url.database}.items():
        monkeypatch.setenv(name, value)
    path = f'/rounds/{active_round}/scenario'
    request_api('PUT' if phase == 'draft' else 'POST', path if phase == 'draft' else path + '/submit',
                player['headers'], command(chain()))
    if phase == 'scored':
        request_api('POST', f'/admin/rounds/{active_round}/score', admin)
    tables = ('users', 'rounds', 'scenarios', 'scoring_results', 'audit_events')
    before = {table: sql(f'SELECT count(*) AS n FROM {table}')[0]['n'] for table in tables}
    result = backup(tmp_path, image_reference='test-code', container=container)
    target = 'aml_restore_' + uuid4().hex
    try:
        report = restore(result['manifest'], target, container=container)
        assert report['counts'] == dict(zip(('users', 'rounds', 'scenarios', 'results', 'audit'), before.values()))
        assert report['duration_seconds'] < 3600 and report['backup_age_seconds'] < 86400
        actual = subprocess.run(pg_command('psql', '-X', '-At', '-d', target, '-c',
                                "SELECT json_build_object('scenario_status',(SELECT status FROM scenarios LIMIT 1),"
                                "'active_sessions',(SELECT count(*) FROM sessions WHERE revoked_at IS NULL))",
                                container=container), check=True, capture_output=True, text=True)
        assert json.loads(actual.stdout) == {'scenario_status': 'editing' if phase == 'draft' else 'scored', 'active_sessions': 0}
        # Repeat restore may not overwrite the existing target database.
        with pytest.raises(subprocess.CalledProcessError):
            restore(result['manifest'], target, container=container)
        print(json.dumps(report))
    finally:
        subprocess.run(pg_command('dropdb', '--if-exists', target, container=container), check=True)
