"""Online PostgreSQL custom-format backup. Connection secrets stay in PG* env."""

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4


def pg_command(tool, *args, container=None):
    prefix = []
    if container:
        prefix = ['docker', 'exec', '-i']
        for name in ('PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD', 'PGDATABASE', 'PGSSLMODE'):
            if name in os.environ:
                prefix += ['-e', name]
        prefix += [container]
    return [*prefix, tool, *args]


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def retention_keep(manifests):
    """Latest successful backup in each of seven days and four ISO weeks."""
    ordered = sorted(manifests, key=lambda item: item['created_at'], reverse=True)
    days, weeks, keep = set(), set(), set()
    for item in ordered:
        stamp = datetime.fromisoformat(item['created_at'])
        day, week = stamp.date(), stamp.isocalendar()[:2]
        daily = day not in days and len(days) < 7
        weekly = week not in weeks and len(weeks) < 4
        if daily or weekly:
            keep.add(item['file'])
        if daily:
            days.add(day)
        if weekly:
            weeks.add(week)
    return keep


def prune(directory):
    directory = Path(directory).resolve()
    manifests = []
    for path in directory.glob('aml-*.json'):
        item = json.loads(path.read_bytes())
        dump = directory / item['file']
        if item.get('format') != 1 or dump.name != path.with_suffix('.dump').name or dump.resolve().parent != directory:
            raise ValueError('Backup manifest contains an unsafe path')
        if checksum(dump) != item['sha256']:
            raise ValueError('Retention refused: backup checksum mismatch')
        manifests.append((path, item))
    keep = retention_keep([item for _, item in manifests])
    removed = []
    for path, item in manifests:
        if item['file'] not in keep:
            (directory / item['file']).unlink()
            path.unlink()
            removed.append(item['file'])
    return removed


def copy_offhost(dump, manifest, destination):
    # SSH host aliases are supported; no arbitrary remote shell syntax.
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*:/[A-Za-z0-9_./-]+', destination):
        raise ValueError('Use an SSH host:/absolute/private/directory destination')
    host, folder = destination.split(':', 1)
    subprocess.run(['scp', '-q', str(dump), destination + '/'], check=True)
    expected = checksum(dump)
    verified = subprocess.run(['ssh', '-o', 'BatchMode=yes', host,
                               'sha256sum', folder.rstrip('/') + '/' + dump.name],
                              check=True, capture_output=True, text=True).stdout.split()[0]
    if verified != expected:
        raise RuntimeError('Off-host backup checksum mismatch')
    # A manifest is the completion marker; publish only after remote verification.
    subprocess.run(['scp', '-q', str(manifest), destination + '/'], check=True)


def backup(directory, *, image_reference, container=None, offhost=None):
    started = time.monotonic()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC)
    name = 'aml-' + stamp.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex[:8]
    temporary = directory / (name + '.partial')
    dump = directory / (name + '.dump')
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            subprocess.run(pg_command('pg_dump', '-Fc', container=container), stdout=stream, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(dump)
    finally:
        temporary.unlink(missing_ok=True)
    manifest = dump.with_suffix('.json')
    result = {'format': 1, 'file': dump.name, 'created_at': stamp.isoformat(),
              'sha256': checksum(dump), 'size_bytes': dump.stat().st_size,
              'image_reference': image_reference, 'duration_seconds': time.monotonic() - started}
    with manifest.open('x', encoding='utf-8') as stream:
        os.chmod(manifest, 0o600)
        json.dump(result, stream, indent=2)
    if offhost:
        copy_offhost(dump, manifest, offhost)
    return {**result, 'offhost_verified': bool(offhost), 'manifest': str(manifest)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--image-reference')
    parser.add_argument('--container')
    parser.add_argument('--offhost', help='SSH host:/private/directory; keys/credentials stay outside argv')
    parser.add_argument('--prune', action='store_true')
    parser.add_argument('--prune-only', action='store_true', help='Apply retention to verified copies on this host')
    args = parser.parse_args()
    if args.prune_only:
        print(json.dumps({'removed': prune(args.directory)}))
        return
    if not args.image_reference:
        parser.error('--image-reference is required for a backup')
    result = backup(args.directory, image_reference=args.image_reference,
                    container=args.container, offhost=args.offhost)
    if args.prune:
        result['removed'] = prune(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
