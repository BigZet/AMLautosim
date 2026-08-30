"""Operational behaviour the audit found stated but not implemented."""

from __future__ import annotations

import asyncio

import psycopg2

from aml_workshop_simulator.api.routers import health
from aml_workshop_simulator.core.security import verify_password
from scripts import seed_database
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def test_changing_the_bootstrap_password_takes_effect(client, db_dsn, monkeypatch):
    """`.env.example` asks the operator to change it; it used to be ignored.

    The account was created on the first run and never touched again, so a
    password that had been committed somewhere stayed valid forever.
    """
    rotated = "rotated-bootstrap-2026"
    monkeypatch.setattr(seed_database.settings, "BOOTSTRAP_ADMIN_PASSWORD", rotated)
    asyncio.run(seed_database.seed())

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT hashed_password, failed_login_count, locked_until "
                "FROM users WHERE email = %s",
                (ADMIN_EMAIL,),
            )
            stored, failures, locked_until = cursor.fetchone()
    finally:
        connection.close()

    assert verify_password(rotated, stored)
    assert not verify_password(ADMIN_PASSWORD, stored)
    # A rotation is also the way out of a lockout.
    assert failures == 0
    assert locked_until is None

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": rotated, "audience": "admin"},
    )
    assert logged_in.status_code == 200, logged_in.text


def test_an_unchanged_password_is_not_rehashed(client, db_dsn):
    """Re-seeding must stay idempotent: bcrypt salts differently every time."""
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT hashed_password FROM users WHERE email = %s", (ADMIN_EMAIL,))
            before = cursor.fetchone()[0]
        asyncio.run(seed_database.seed())
        with connection.cursor() as cursor:
            cursor.execute("SELECT hashed_password FROM users WHERE email = %s", (ADMIN_EMAIL,))
            after = cursor.fetchone()[0]
    finally:
        connection.close()

    assert before == after


def test_readiness_fails_when_the_revision_history_cannot_be_read(client, monkeypatch):
    """An unverifiable migration state is not a healthy one.

    The hand-rolled parser returned an empty set when it could not find the
    directory, and an empty set passed the comparison: readiness answered
    «head» having checked nothing.
    """
    assert client.get("/health/ready").json()["checks"]["migrations"] == "head"

    def unreadable() -> frozenset[str]:
        raise RuntimeError("no such revision directory")

    monkeypatch.setattr(health, "_expected_heads", unreadable)
    response = client.get("/health/ready")

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["migrations"] == "revision history unreadable"


def test_the_heads_come_from_alembic_itself(client):
    """Alembic is the authority on what a head revision is."""
    heads = health._expected_heads()
    assert heads, "the revision history must not be empty"
    applied = client.get("/health/ready").json()
    assert applied["checks"]["migrations"] == "head"
