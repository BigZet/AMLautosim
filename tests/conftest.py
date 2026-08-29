"""Shared PostgreSQL 16 test fixtures.

Every test level except the pure-domain unit tests runs against a real
PostgreSQL 16 database (`aml_simulator_test` by default). SQLite is never used:
partial unique indexes, JSONB, row locks and `NUMERIC` rounding must behave
exactly as they do in production.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://aml:aml@localhost:5432/postgres"
)
TEST_DB_NAME = os.environ.get("TEST_DATABASE_NAME", "aml_simulator_test")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql+asyncpg://aml:aml@localhost:5432/{TEST_DB_NAME}",
)

# Must be set before any application module reads the settings singleton.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DB_POOL_DISABLED"] = "true"
os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "admin12345")

ADMIN_EMAIL = os.environ["BOOTSTRAP_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["BOOTSTRAP_ADMIN_PASSWORD"]
PARTICIPANT_PASSWORD = "correct-horse-42"

TABLES = (
    "audit_events",
    "leaderboard_adjustments",
    "scoring_results",
    "scenarios",
    "sessions",
    "rounds",
    "users",
    "action_cards",
)


def _sync_dsn() -> str:
    return TEST_DATABASE_URL.replace("+asyncpg", "").replace(
        "postgresql://", "postgresql://"
    )


def _create_database_if_missing() -> None:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    connection = psycopg2.connect(ADMIN_DSN)
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME))
                )
    finally:
        connection.close()


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Create and migrate the test database once per session."""
    try:
        _create_database_if_missing()
    except Exception as exc:  # pragma: no cover - environment problem, not a test failure
        pytest.exit(f"PostgreSQL 16 is required for the test suite: {exc}", returncode=3)
    _migrate()
    yield


@pytest.fixture()
def db_dsn(database: None) -> str:
    return _sync_dsn()


@pytest.fixture()
def clean_database(database: None) -> Iterator[None]:
    """Truncate every table and re-seed the catalog before each test."""
    import asyncio

    import psycopg2

    connection = psycopg2.connect(_sync_dsn())
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE TABLE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"
            )
    finally:
        connection.close()

    from scripts.seed_database import seed

    asyncio.run(seed(activate_round=False))
    yield


@pytest.fixture()
def client(clean_database: None) -> Iterator[Any]:
    """FastAPI test client bound to a single event loop for its lifetime."""
    from fastapi.testclient import TestClient

    from src.aml_workshop_simulator.api.main import app

    # Unhandled server errors must surface as the documented envelope, exactly
    # as they would behind uvicorn, instead of propagating into the test.
    # A real peer address is supplied so the request metadata the API records
    # (and the trusted-proxy rules around it) can be exercised.
    with TestClient(
        app, raise_server_exceptions=False, client=("127.0.0.1", 50000)
    ) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers(client: Any) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "audience": "admin"},
    )
    assert response.status_code == 200, response.text
    return {"X-Session-ID": response.json()["session_id"]}


def register_participant(
    client: Any, email: str | None = None, display_name: str = "Участник"
) -> dict[str, Any]:
    """Register and log in one participant, returning identity plus headers."""
    email = email or f"p{uuid.uuid4().hex[:10]}@example.com"
    created = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": display_name,
            "password": PARTICIPANT_PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PARTICIPANT_PASSWORD, "audience": "play"},
    )
    assert logged_in.status_code == 200, logged_in.text
    payload = logged_in.json()
    return {
        "id": created.json()["id"],
        "email": email,
        "display_name": display_name,
        "session_id": payload["session_id"],
        "headers": {"X-Session-ID": payload["session_id"]},
    }


@pytest.fixture()
def participant(client: Any) -> dict[str, Any]:
    return register_participant(client)


@pytest.fixture()
def second_participant(client: Any) -> dict[str, Any]:
    return register_participant(client, display_name="Второй участник")


@pytest.fixture()
def active_round(client: Any, admin_headers: dict[str, str]) -> dict[str, Any]:
    """Activate the seeded demo round and return it."""
    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    draft = next(item for item in rounds if item["status"] == "draft")
    response = client.post(
        f"/api/v1/admin/rounds/{draft['id']}/activate",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def cards(client: Any, active_round: dict[str, Any]) -> dict[str, dict[str, Any]]:
    response = client.get(f"/api/v1/rounds/{active_round['id']}/cards")
    assert response.status_code == 200, response.text
    return {card["code"]: card for card in response.json()}


@pytest.fixture()
def full_round(client: Any, admin_headers: dict[str, str]) -> dict[str, Any]:
    """A round configured the *legacy* way: all eight cards, nothing hidden.

    Rounds created before the parameter surface was reduced look like this, and
    their drafts must keep working. It is also the configuration that lets the
    channel/parameter matrix be exercised across the whole catalog.
    """
    from src.aml_workshop_simulator.domain.rules import REFERENCE_GAME_CONFIG

    catalog = client.get("/api/v1/admin/action-cards", headers=admin_headers).json()
    config = {
        key: value
        for key, value in REFERENCE_GAME_CONFIG.items()
        if key != "operations"
    }
    config["schema_version"] = 2
    config["card_versions"] = [
        {"id": card["id"], "code": card["code"], "version": card["version"]}
        for card in catalog
    ]

    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    draft = next(item for item in rounds if item["status"] == "draft")
    updated = client.put(
        f"/api/v1/admin/rounds/{draft['id']}",
        json={
            "expected_config_revision": draft["config_revision"],
            "game_config": config,
        },
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    response = client.post(
        f"/api/v1/admin/rounds/{draft['id']}/activate",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def full_cards(client: Any, full_round: dict[str, Any]) -> dict[str, dict[str, Any]]:
    response = client.get(f"/api/v1/rounds/{full_round['id']}/cards")
    assert response.status_code == 200, response.text
    return {card["code"]: card for card in response.json()}
