from datetime import UTC, datetime, timedelta
import json

import pytest

from scripts.ops.backup_database import retention_keep
from scripts.ops.restore_database import restore


def test_retention_preserves_seven_daily_and_four_weekly():
    now = datetime(2026, 9, 25, tzinfo=UTC)
    rows = [{'file': str(i), 'created_at': (now - timedelta(days=i)).isoformat()} for i in range(50)]
    kept = retention_keep(rows)
    assert {str(i) for i in range(7)} <= kept
    assert len(kept) <= 11
    assert len({datetime.fromisoformat(row['created_at']).isocalendar()[:2] for row in rows if row['file'] in kept}) == 4


def test_corrupt_backup_rejected_before_creating_database(tmp_path, monkeypatch):
    (tmp_path / 'backup.dump').write_bytes(b'broken')
    manifest = tmp_path / 'backup.json'
    manifest.write_text(json.dumps({'file': 'backup.dump', 'sha256': 'wrong'}))
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: pytest.fail('Must not open database'))
    with pytest.raises(ValueError, match='checksum'):
        restore(manifest, 'aml_restore_test')


@pytest.mark.parametrize('target', ['postgres', 'aml_simulator', 'aml_restore_foo; DROP DATABASE postgres'])
def test_restore_refuses_unscoped_database(target):
    with pytest.raises(ValueError, match='NEW'):
        restore('unused', target)
