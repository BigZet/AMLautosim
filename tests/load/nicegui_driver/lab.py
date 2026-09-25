"""Start/stop a disposable loopback-only proxy workshop; saves private state locally."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[3]


def start(image, destination, count, *, workers=1, pool_size=5, overflow=10):
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    project = "aml-load-" + uuid4().hex[:10]
    env = dict(
        os.environ,
        AML_CI_IMAGE=image,
        AML_CI_DB_PASSWORD=secrets.token_hex(24),
        AML_CI_ADMIN_PASSWORD=secrets.token_hex(24),
        AML_CI_STORAGE_SECRET=secrets.token_hex(32),
    )
    token = secrets.token_hex(32)
    nginx = (ROOT / "deploy/nicegui.nginx.conf").read_text(encoding="utf-8")
    # Lab has only loopback host publishing; this override is NEVER for production.
    (destination / "nginx.conf").write_text(
        nginx.replace("default 0;", "default 1;"), encoding="utf-8"
    )
    override = {
        "services": {
            "api": {
                "environment": {
                    "METRICS_TOKEN": token,
                    "API_WORKERS": workers,
                    "DB_POOL_SIZE": pool_size,
                    "DB_POOL_OVERFLOW": overflow,
                }
            },
            "ui": {"environment": {"METRICS_TOKEN": token}},
            "ingress": {
                "volumes": [
                    str((destination / "nginx.conf").resolve()).replace("\\", "/")
                    + ":/etc/nginx/conf.d/default.conf:ro"
                ]
            },
        }
    }
    (destination / "override.json").write_text(json.dumps(override), encoding="utf-8")
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "-f",
        str(ROOT / "deploy/compose.smoke.yml"),
        "-f",
        str(destination / "override.json"),
    ]
    state = {
        "project": project,
        "command": command,
        "environment": {k: v for k, v in env.items() if k.startswith("AML_CI_")},
        "metrics_token": token,
        "api_settings": {
            "workers": workers,
            "pool_size": pool_size,
            "overflow": overflow,
        },
    }
    state_path = destination / "private-state.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.chmod(state_path, 0o600)

    def compose(*args):
        return subprocess.check_output([*command, *args], env=env, text=True).strip()

    compose("up", "--detach", "--wait", "--wait-timeout", "240")
    state.update(
        {
            name: "http://" + compose("port", service, port)
            for name, service, port in [
                ("api", "api", "8000"),
                ("ui", "ui", "8080"),
                ("url", "ingress", "80"),
            ]
        }
    )
    state["image_id"] = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    with httpx.Client(base_url=state["api"] + "/api/v1", timeout=60) as client:
        response = client.post(
            "/auth/login",
            json={
                "email": "admin@example.com",
                "password": env["AML_CI_ADMIN_PASSWORD"],
                "audience": "admin",
            },
        )
        response.raise_for_status()
        headers = {"X-Session-ID": response.json()["session_id"]}
        response = client.post(
            "/admin/rounds", headers=headers, json={"title": "Disposable load workshop"}
        )
        response.raise_for_status()
        state["round_id"] = response.json()["id"]
        client.post(
            f"/admin/rounds/{state['round_id']}/start", headers=headers
        ).raise_for_status()
        accounts = [
            {"email": f"load-{i}@example.com", "password": secrets.token_hex(16)}
            for i in range(count)
        ]
        started = time.monotonic()
        for i, account in enumerate(accounts):
            client.post(
                "/auth/register", json={**account, "display_name": f"Load {i}"}
            ).raise_for_status()
        state["registration_seconds"] = time.monotonic() - started
    (destination / "accounts.json").write_text(json.dumps(accounts), encoding="utf-8")
    os.chmod(destination / "accounts.json", 0o600)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: state[k]
                for k in [
                    "project",
                    "url",
                    "api",
                    "ui",
                    "round_id",
                    "image_id",
                    "registration_seconds",
                ]
            }
        )
    )


def stop(destination):
    state = json.loads((destination / "private-state.json").read_text(encoding="utf-8"))
    if not state["project"].startswith("aml-load-"):
        raise ValueError("refusing_unowned_project")
    subprocess.run(
        [*state["command"], "down", "--volumes", "--remove-orphans"],
        env=dict(os.environ, **state["environment"]),
        check=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["start", "stop"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--image", default="aml-remediation:t07")
    parser.add_argument("--accounts", type=int, default=60)
    parser.add_argument("--workers", type=int, choices=[1, 2, 4], default=1)
    parser.add_argument("--pool-size", type=int, choices=range(1, 101), default=5)
    parser.add_argument("--overflow", type=int, choices=range(0, 101), default=10)
    args = parser.parse_args()
    if args.mode == "start":
        start(
            args.image,
            args.directory.resolve(),
            args.accounts,
            workers=args.workers,
            pool_size=args.pool_size,
            overflow=args.overflow,
        )
    else:
        stop(args.directory.resolve())
