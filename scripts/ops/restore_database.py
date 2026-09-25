"""Restore verified backup into a NEW database; revoke restored sessions."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import time

from scripts.ops.backup_database import checksum, pg_command


def restore(manifest_path, target_database, *, container=None):
    started = time.monotonic()
    if not re.fullmatch(r'aml_restore_[a-z0-9_]{1,40}', target_database):
        raise ValueError('Target must be a NEW aml_restore_<name> database')
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_bytes())
    dump = manifest_path.parent / manifest['file']
    if dump.resolve().parent != manifest_path.parent or checksum(dump) != manifest['sha256']:
        raise ValueError('Backup checksum/path verification failed')
    # No --clean, DROP, or replacement of an existing database. createdb fails closed.
    subprocess.run(pg_command('createdb', target_database, container=container), check=True)
    with dump.open('rb') as stream:
        subprocess.run(pg_command('pg_restore', '--exit-on-error', '--single-transaction',
                                  '--no-owner', '-d', target_database, container=container),
                       stdin=stream, check=True)
    subprocess.run(pg_command('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-d', target_database,
                              '-c', "UPDATE sessions SET revoked_at=now(), revoke_reason='backup_restore' WHERE revoked_at IS NULL",
                              container=container), check=True, capture_output=True)
    counts = subprocess.run(pg_command('psql', '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-d', target_database,
                                      '-c', "SELECT json_build_object('users',(SELECT count(*) FROM users),"
                                      "'rounds',(SELECT count(*) FROM rounds),'scenarios',(SELECT count(*) FROM scenarios),"
                                      "'results',(SELECT count(*) FROM scoring_results),'audit',(SELECT count(*) FROM audit_events))",
                                      container=container), check=True, capture_output=True, text=True).stdout
    return {'database': target_database, 'image_reference': manifest['image_reference'],
            'duration_seconds': time.monotonic() - started,
            'backup_age_seconds': (datetime.now(UTC) - datetime.fromisoformat(manifest['created_at'])).total_seconds(),
            'counts': json.loads(counts), 'sessions_revoked': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--target-database', required=True)
    parser.add_argument('--container')
    args = parser.parse_args()
    print(json.dumps(restore(args.manifest, args.target_database, container=args.container), indent=2))


if __name__ == '__main__':
    main()
