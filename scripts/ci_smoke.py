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
        asyncio.run(check_transport(f'http://{ui}'))
        print(json.dumps({'image': image, 'project': project, 'readiness': readiness,
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
