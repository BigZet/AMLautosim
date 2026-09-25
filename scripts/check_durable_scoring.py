"""Exercise the real worker only in a disposable lab created by lab.py."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import httpx


# Fixture insertion isolates calculation capacity from registration throughput.
# Passwords are deliberately unusable; these accounts never authenticate.
SEED = """
import asyncio, json, sys
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4
from src.aml_workshop_simulator.db.session import AsyncSessionLocal
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.models.scenarios import Scenario
async def main():
    data = json.load(sys.stdin)
    async with AsyncSessionLocal() as db:
        row = await db.get(Round, data['round_id'])
        assert row.status == 'active'
        cards = {(c['code'], c['version']): c['id'] for c in row.game_config['card_snapshots']}
        for i in range(data['count']):
            user = User(email=f"worker-fixture-{uuid4()}@example.invalid", role='participant',
                        display_name=f'Fixture {i}', hashed_password='!disabled-fixture')
            db.add(user)
            await db.flush()
            steps = deepcopy(data['steps'])
            for step in steps:
                step['step_id'] = str(uuid4())
                step['card']['id'] = cards[(step['card']['code'], step['card']['version'])]
            db.add(Scenario(round_id=row.id, participant_id=user.id, status='submitted',
                            steps=steps, revision=1, updated_at=datetime.now(UTC),
                            submitted_at=datetime.now(UTC)))
        await db.commit()
asyncio.run(main())
"""


def check(directory, output):
    state = json.loads((directory / "private-state.json").read_bytes())
    if not state["project"].startswith("aml-load-"):
        raise ValueError("refusing_unowned_lab")
    command = state["command"]
    if (
        "--project-name" not in command
        or command[command.index("--project-name") + 1] != state["project"]
    ):
        raise ValueError("lab_project_mismatch")
    env = dict(os.environ, **state["environment"])

    def compose(*args, data=None):
        return subprocess.run(
            [*command, *args],
            env=env,
            input=data,
            text=True,
            check=True,
            capture_output=True,
        ).stdout.strip()

    def counts(round_id):
        query = (
            "SELECT count(*), count(DISTINCT r.scenario_id), "
            "count(DISTINCT (r.risk_score,r.game_score,r.resource_score)) "
            "FROM scoring_results r JOIN scenarios s ON s.id=r.scenario_id "
            f"WHERE s.round_id={int(round_id)}"
        )
        return [
            int(x)
            for x in compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "aml_ci",
                "-d",
                "aml_ci",
                "-Atc",
                query,
            ).split("|")
        ]

    fixture = Path("tests/fixtures/game_classifier_chain.json")
    steps = json.loads(fixture.read_bytes())
    report = {
        "image_id": state["image_id"],
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "fixture_setup": "direct disposable DB insert; real API enqueue, worker, publication",
        "runs": [],
    }
    with httpx.Client(base_url=state["api"] + "/api/v1", timeout=30) as client:
        response = client.post(
            "/auth/login",
            json={
                "email": "admin@example.com",
                "password": env["AML_CI_ADMIN_PASSWORD"],
                "audience": "admin",
            },
        )
        response.raise_for_status()
        client.headers["X-Session-ID"] = response.json()["session_id"]
        for count in (60, 300):
            current = client.get("/admin/rounds/current").json()
            response = client.post(f"/admin/rounds/{current['id']}/restart")
            response.raise_for_status()
            round_id = response.json()["id"]
            client.post(f"/admin/rounds/{round_id}/start").raise_for_status()
            compose("stop", "scoring-worker")
            compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                SEED,
                data=json.dumps({"round_id": round_id, "count": count, "steps": steps}),
            )
            started = time.monotonic()
            response = client.post(f"/admin/rounds/{round_id}/score")
            assert response.status_code == 202, response.text
            job = response.json()
            assert (job["state"], job["total"]) == ("queued", count), job
            job_id = job["job_id"]
            time.sleep(1)
            assert (
                client.get(f"/admin/scoring-jobs/{job_id}").json()["state"] == "queued"
            )
            assert counts(round_id)[0] == 0
            compose("start", "scoring-worker")
            killed = False
            samples = []
            while time.monotonic() - started < 600:
                response = client.get(f"/admin/scoring-jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                samples.append(
                    {
                        "seconds": time.monotonic() - started,
                        **{k: job[k] for k in ("state", "done", "total", "attempt")},
                    }
                )
                if (
                    count == 300
                    and not killed
                    and job["state"] == "running"
                    and job["done"] >= 20
                ):
                    compose("kill", "-s", "SIGKILL", "scoring-worker")
                    assert counts(round_id)[0] == 0
                    same = client.post(f"/admin/rounds/{round_id}/score").json()
                    assert same["job_id"] == job_id
                    compose("start", "scoring-worker")
                    killed = True
                if job["state"] == "completed":
                    break
                assert job["state"] in ("queued", "running"), job
                time.sleep(0.5)
            else:
                raise AssertionError("durable_scoring_timed_out")
            assert job["done"] == count and job["summary"]["scored_count"] == count
            assert job["attempt"] == (2 if count == 300 else 1), job
            assert counts(round_id) == [count, count, 1]
            run = {
                "count": count,
                "seconds_including_queue_and_recovery": time.monotonic() - started,
                "worker_killed": killed,
                "summary": job["summary"],
                "attempt": job["attempt"],
                "results": count,
                "unique_results": count,
                "samples": samples,
            }
            report["runs"].append(run)
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                json.dumps({k: v for k, v in run.items() if k != "samples"}), flush=True
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check(args.directory, args.output)
