"""Verify one built image with disposable PostgreSQL, API, UI and WebSocket."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import urllib.request
from uuid import uuid4

from scripts.check_nicegui_transport import main as check_transport


def smoke(image: str) -> None:
    root = Path(__file__).resolve().parents[1]
    project = 'aml-smoke-' + uuid4().hex[:12]
    env = dict(os.environ, AML_CI_IMAGE=image,
               AML_CI_DB_PASSWORD=secrets.token_hex(24),
               AML_CI_ADMIN_PASSWORD=secrets.token_hex(24),
               AML_CI_STORAGE_SECRET=secrets.token_hex(32))
    command = ['docker', 'compose', '--project-name', project,
               '-f', str(root / 'deploy/compose.smoke.yml')]

    def compose(*args, capture=False):
        return subprocess.run([*command, *args], env=env, cwd=root, check=True,
                              capture_output=capture, text=True)

    try:
        compose('up', '--detach', '--wait', '--wait-timeout', '180')
        api = compose('port', 'api', '8000', capture=True).stdout.strip()
        ui = compose('port', 'ui', '8080', capture=True).stdout.strip()
        with urllib.request.urlopen(f'http://{api}/health/ready', timeout=15) as response:
            readiness = json.load(response)
        if readiness['status'] != 'ready':
            raise RuntimeError('Image readiness failed')
        # Re-run the release command against a restored copy, never the live DB.
        dump = subprocess.run(
            [*command, 'exec', '-T', 'db', 'pg_dump', '-U', 'aml_ci', '-Fc', 'aml_ci'],
            env=env, cwd=root, check=True, capture_output=True,
        ).stdout
        compose('exec', '-T', 'db', 'createdb', '-U', 'aml_ci', 'aml_upgrade')
        subprocess.run(
            [*command, 'exec', '-T', 'db', 'pg_restore', '-U', 'aml_ci',
             '--exit-on-error', '-d', 'aml_upgrade'],
            input=dump, env=env, cwd=root, check=True,
        )
        query = 'SELECT id, email, hashed_password FROM users ORDER BY id'
        before = compose('exec', '-T', 'db', 'psql', '-U', 'aml_ci', '-d',
                         'aml_upgrade', '-Atc', query, capture=True).stdout
        compose('run', '--rm', '--no-deps', '-e', 'POSTGRES_DB=aml_upgrade', 'release')
        after = compose('exec', '-T', 'db', 'psql', '-U', 'aml_ci', '-d',
                        'aml_upgrade', '-Atc', query, capture=True).stdout
        if not before or before != after:
            raise RuntimeError('Release changed restored accounts')
        asyncio.run(check_transport(f'http://{ui}'))
        print(json.dumps({'image': image, 'project': project, 'readiness': readiness,
                          'restored_copy_release': 'passed',
                          'http_cookie_websocket': 'passed'}))
    except Exception:
        subprocess.run([*command, 'logs', '--no-color', '--tail', '80'], env=env, cwd=root)
        raise
    finally:
        compose('down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    smoke(parser.parse_args().image)
