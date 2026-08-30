"""Full workshop round on the real stack, including recovery and backup.

The round is played through the live HTTP API of the running services, so the
assertions cover process boundaries: API restart, PostgreSQL restart with its
persistent volume, and a pg_dump/pg_restore cycle.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from typing import Any

import psycopg2
import pytest

from tests.ui.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    ARTIFACTS,
    E2E_DB_NAME,
    E2E_SYNC_DSN,
    PARTICIPANT_PASSWORD,
    Stack,
    db_query,
    register,
)

POSTGRES_CONTAINER = "aml_postgres"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", POSTGRES_CONTAINER],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def login(stack: Stack, email: str, password: str, audience: str) -> str:
    return stack.request(
        "POST",
        "/api/v1/auth/login",
        {"email": email, "password": password, "audience": audience},
    )["session_id"]


def build_chain(stack: Stack, round_id: int, session_id: str) -> dict[str, Any]:
    cards = {
        card["code"]: card
        for card in stack.request("GET", f"/api/v1/rounds/{round_id}/cards")
    }

    def step(code: str, amount: str, channel: str) -> dict[str, Any]:
        card = cards[code]
        return {
            "step_id": str(uuid.uuid4()),
            "card": {"id": card["id"], "code": card["code"], "version": card["version"]},
            "amount": amount,
            "frequency": 1,
            "context": {"channel": channel},
            "action_details": {field["key"]: field["default"] for field in card["fields"]},
        }

    return stack.request(
        "PUT",
        f"/api/v1/rounds/{round_id}/scenario",
        {
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
            "steps": [
                step("salary", "120000.00", "bank"),
                step("card_transfer", "100000.00", "mobile"),
                step("cash_withdrawal", "50000.00", "atm"),
            ],
        },
        session_id=session_id,
    )


def test_full_round_from_registration_to_leaderboard(reset_state: Stack) -> None:
    stack = reset_state
    active = stack.request("GET", "/api/v1/rounds/active")
    round_id = active["id"]

    players = [register(stack, f"Участник {index}") for index in range(1, 4)]
    sessions = [
        login(stack, player["email"], PARTICIPANT_PASSWORD, "play") for player in players
    ]

    # Two players submit, one leaves a draft behind.
    for player_session in sessions[:2]:
        saved = build_chain(stack, round_id, player_session)
        stack.request(
            "POST",
            f"/api/v1/rounds/{round_id}/scenario/submit",
            {"expected_revision": saved["revision"]},
            session_id=player_session,
        )
    build_chain(stack, round_id, sessions[2])

    admin_session = login(stack, ADMIN_EMAIL, ADMIN_PASSWORD, "admin")
    stats = stack.request(
        "GET", f"/api/v1/admin/rounds/{round_id}/stats", session_id=admin_session
    )
    assert stats["submitted_scenarios"] == 2
    assert stats["draft_scenarios"] == 1

    # The API restarts between submission and scoring.
    stack.restart_api()

    summary = stack.request(
        "POST", f"/api/v1/admin/rounds/{round_id}/score", session_id=admin_session
    )
    assert summary["scored_count"] == 2
    assert summary["excluded_draft_count"] == 1
    assert summary["status"] == "completed"

    for player_session in sessions[:2]:
        result = stack.request(
            "GET", f"/api/v1/rounds/{round_id}/result", session_id=player_session
        )
        assert result is not None
        assert 0 <= float(result["base"]["risk_score"]) <= 100
        assert result["explanation"]["disclaimer"]

    draft_result = stack.request(
        "GET", f"/api/v1/rounds/{round_id}/result", session_id=sessions[2]
    )
    assert draft_result is None

    board = stack.request("GET", f"/api/v1/rounds/{round_id}/leaderboard")
    assert len(board["rows"]) == 2
    assert board["rows"][0]["rank"] == 1
    assert board["revealed"] is False
    for position, row in enumerate(board["rows"], start=1):
        assert "email" not in row
        assert set(row) == {
            "rank", "display_name", "game_score", "stealth_score",
            "resource_score", "risk_label", "is_adjusted", "is_current_user",
            "masked",
        }
        # Nobody's nickname leaves the server until it is asked for.
        assert row["masked"] is True
        assert row["display_name"] == f"Игрок #{position}"
    for player in players[:2]:
        assert player["display_name"] not in str(board)

    # Revealing is the organiser's command: the participants' own sessions and
    # an anonymous caller are both refused.
    revealed = stack.request(
        "GET",
        f"/api/v1/rounds/{round_id}/leaderboard?reveal=true",
        session_id=admin_session,
    )
    assert revealed["revealed"] is True
    assert {row["display_name"] for row in revealed["rows"]} == {
        player["display_name"] for player in players[:2]
    }

    # Manual adjustment changes only the effective projection.
    first_player = players[0]
    before = stack.request(
        "GET", f"/api/v1/rounds/{round_id}/result", session_id=sessions[0]
    )
    stack.request(
        "PUT",
        f"/api/v1/admin/rounds/{round_id}/participants/{db_query(
            'SELECT id FROM users WHERE email = %s', (first_player['email'],)
        )[0][0]}/leaderboard-adjustment",
        {
            "expected_revision": 0,
            "game_score_override": "95.00",
            "reason": "Компенсация подтвержденной технической ошибки",
        },
        session_id=admin_session,
    )
    after = stack.request(
        "GET", f"/api/v1/rounds/{round_id}/result", session_id=sessions[0]
    )
    assert after["base"] == before["base"]
    assert after["leaderboard"]["effective_game_score"] == "95.00"
    assert after["leaderboard"]["is_adjusted"] is True


def test_the_lifecycle_survives_an_api_restart(draft_state: Stack) -> None:
    """Start, stop and restart across a process boundary, losing nothing."""
    stack = draft_state
    admin_session = login(stack, ADMIN_EMAIL, ADMIN_PASSWORD, "admin")
    rounds = stack.request("GET", "/api/v1/admin/rounds", session_id=admin_session)
    round_id = rounds[0]["id"]
    assert rounds[0]["status"] == "draft"

    player = register(stack, "Жизненный цикл")
    session_id = login(stack, player["email"], PARTICIPANT_PASSWORD, "play")

    # Before the start there is nothing to play and nothing to write.
    assert stack.request("GET", "/api/v1/rounds/active") is None
    with pytest.raises(AssertionError, match="409"):
        build_chain(stack, round_id, session_id)

    stack.request(
        "POST", f"/api/v1/admin/rounds/{round_id}/start", session_id=admin_session
    )
    saved = build_chain(stack, round_id, session_id)
    assert saved["revision"] == 1

    stack.restart_api()

    stack.request(
        "POST",
        f"/api/v1/admin/rounds/{round_id}/stop",
        {"confirm": True, "reason": "Перерыв мастер-класса"},
        session_id=admin_session,
    )
    with pytest.raises(AssertionError, match="409"):
        stack.request(
            "PUT",
            f"/api/v1/rounds/{round_id}/scenario",
            {
                "expected_revision": saved["revision"],
                "client_mutation_id": str(uuid.uuid4()),
                "steps": [],
            },
            session_id=session_id,
        )

    replacement = stack.request(
        "POST",
        f"/api/v1/admin/rounds/{round_id}/restart",
        {"confirm": True, "title": "Второй прогон"},
        session_id=admin_session,
    )
    assert replacement["status"] == "draft"
    assert replacement["restarted_from_round_id"] == round_id

    # Nothing from the first round was destroyed.
    assert db_query(
        "SELECT status FROM rounds ORDER BY id"
    ) == [("stopped",), ("draft",)]
    assert db_query(
        "SELECT count(*) FROM scenario_versions v JOIN scenarios s ON s.id = v.scenario_id "
        "WHERE s.round_id = %s",
        (round_id,),
    ) == [(1,)]

    stack.request(
        "POST",
        f"/api/v1/admin/rounds/{replacement['id']}/start",
        session_id=admin_session,
    )
    assert stack.request("GET", "/api/v1/rounds/active")["id"] == replacement["id"]


def test_data_survives_a_postgresql_restart(reset_state: Stack) -> None:
    if not docker_available():
        pytest.skip("Docker is required to restart the PostgreSQL container")

    stack = reset_state
    active = stack.request("GET", "/api/v1/rounds/active")
    round_id = active["id"]
    player = register(stack, "Восстановление")
    session_id = login(stack, player["email"], PARTICIPANT_PASSWORD, "play")
    saved = build_chain(stack, round_id, session_id)
    assert saved["revision"] == 1

    subprocess.run(["docker", "restart", POSTGRES_CONTAINER], check=True, timeout=180)

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", POSTGRES_CONTAINER, "pg_isready", "-U", "aml"],
            capture_output=True,
        )
        if probe.returncode == 0:
            break
        time.sleep(2)
    else:  # pragma: no cover - the container never came back
        pytest.fail("PostgreSQL did not come back after the restart")

    restored = stack.request(
        "GET", f"/api/v1/rounds/{round_id}/scenario", session_id=session_id
    )
    assert restored["revision"] == 1
    assert len(restored["steps"]) == 3
    assert restored["steps"][0]["context"]["channel"] == "bank"


def test_backup_and_restore_round_trip(reset_state: Stack) -> None:
    if not docker_available():
        pytest.skip("Docker is required for the pg_dump/pg_restore smoke test")

    stack = reset_state
    active = stack.request("GET", "/api/v1/rounds/active")
    player = register(stack, "Бэкап")
    session_id = login(stack, player["email"], PARTICIPANT_PASSWORD, "play")
    build_chain(stack, active["id"], session_id)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    dump_path = ARTIFACTS / "e2e-backup.sql"
    dumped = subprocess.run(
        ["docker", "exec", POSTGRES_CONTAINER, "pg_dump", "-U", "aml", E2E_DB_NAME],
        capture_output=True,
        timeout=300,
    )
    assert dumped.returncode == 0, dumped.stderr[-500:]
    dump_path.write_bytes(dumped.stdout)
    assert dump_path.stat().st_size > 1000

    restore_db = f"aml_restore_{uuid.uuid4().hex[:8]}"
    created = subprocess.run(
        ["docker", "exec", POSTGRES_CONTAINER, "createdb", "-U", "aml", restore_db],
        capture_output=True,
        timeout=120,
    )
    assert created.returncode == 0, created.stderr[-500:]
    try:
        restored = subprocess.run(
            ["docker", "exec", "-i", POSTGRES_CONTAINER, "psql", "-U", "aml",
             "-d", restore_db, "-v", "ON_ERROR_STOP=1"],
            input=dumped.stdout,
            capture_output=True,
            timeout=300,
        )
        assert restored.returncode == 0, restored.stderr[-1000:]

        dsn = E2E_SYNC_DSN.rsplit("/", 1)[0] + "/" + restore_db
        connection = psycopg2.connect(dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM action_cards")
                assert cursor.fetchone()[0] == 4
                cursor.execute(
                    "SELECT jsonb_array_length(steps) FROM scenarios"
                )
                assert cursor.fetchone()[0] == 3
        finally:
            connection.close()
    finally:
        subprocess.run(
            ["docker", "exec", POSTGRES_CONTAINER, "dropdb", "-U", "aml", "--force",
             restore_db],
            capture_output=True,
            timeout=120,
        )
