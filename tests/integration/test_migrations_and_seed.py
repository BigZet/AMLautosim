"""Schema, constraints, indexes and seed idempotency on PostgreSQL 16."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from decimal import Decimal

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from tests.conftest import ADMIN_DSN, ROOT, TEST_DATABASE_URL


def sync_dsn(database: str) -> str:
    base = TEST_DATABASE_URL.replace("+asyncpg", "")
    return base.rsplit("/", 1)[0] + "/" + database


def test_server_is_postgresql_16(db_dsn) -> None:
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            version = cursor.fetchone()[0]
    finally:
        connection.close()
    assert version.split(".")[0] == "16", version


def test_clean_database_reaches_alembic_head_and_seeds_idempotently() -> None:
    """The documented bootstrap command works on an empty database, twice.

    It runs in a subprocess so the check exercises the real entry point rather
    than a patched in-process engine.
    """
    scratch = f"aml_migrate_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(ADMIN_DSN)
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
    finally:
        admin.close()

    environment = dict(os.environ)
    environment["DATABASE_URL"] = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/" + scratch
    environment["PYTHONIOENCODING"] = "utf-8"
    try:
        for attempt in range(2):
            completed = subprocess.run(
                [sys.executable, "-m", "scripts.seed_database", "--migrate"],
                cwd=str(ROOT),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )
            assert completed.returncode == 0, (attempt, completed.stdout, completed.stderr)
            assert "cards=4" in completed.stdout

        connection = psycopg2.connect(sync_dsn(scratch))
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM action_cards")
                assert cursor.fetchone()[0] == 4
                cursor.execute("SELECT count(*) FROM users WHERE role = 'admin'")
                assert cursor.fetchone()[0] == 1
                cursor.execute("SELECT count(*) FROM rounds")
                assert cursor.fetchone()[0] == 1
                cursor.execute("SELECT count(*) FROM audit_events")
                assert cursor.fetchone()[0] == 1
                cursor.execute("SELECT version_num FROM alembic_version")
                assert cursor.fetchone()[0] == "e84a6d2c190f"
        finally:
            connection.close()
    finally:
        admin = psycopg2.connect(ADMIN_DSN)
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(scratch)
                    )
                )
        finally:
            admin.close()


def test_documented_indexes_exist(db_dsn) -> None:
    expected = {
        "uq_rounds_single_active",
        "ix_users_blocked",
        "ix_rounds_status_created_at",
        "ix_scenarios_round_status",
        "ix_scenarios_participant_updated",
        "ix_scoring_results_board",
        "ix_sessions_user_id",
        "ix_audit_events_round_created",
        "ix_audit_events_actor_created",
        "ix_audit_events_scenario_created",
        "uq_audit_events_idempotency",
        "uq_scenarios_round_id_participant_id",
        "uq_action_cards_code_version",
        "uq_scoring_results_scenario_id",
        "uq_leaderboard_adjustments_scenario_id",
    }
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            found = {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()
    assert expected <= found, expected - found


def test_money_columns_use_numeric_14_2(db_dsn) -> None:
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'numeric'"
            )
            rows = {(t, c): (p, s) for t, c, p, s in cursor.fetchall()}
    finally:
        connection.close()
    assert rows[("action_cards", "min_amount")] == (14, 2)
    assert rows[("action_cards", "max_amount")] == (14, 2)
    assert rows[("action_cards", "fee_rate")] == (8, 6)
    assert rows[("action_cards", "risk_weight")] == (8, 2)


def test_unique_scenario_per_round_and_participant(db_dsn, client, participant, active_round) -> None:
    connection = psycopg2.connect(db_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO scenarios (round_id, participant_id, status, steps, revision, "
                "updated_at) VALUES (%s, %s, 'draft', '[]'::jsonb, 1, now())",
                (active_round["id"], participant["id"]),
            )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    "INSERT INTO scenarios (round_id, participant_id, status, steps, revision, "
                    "updated_at) VALUES (%s, %s, 'draft', '[]'::jsonb, 1, now())",
                    (active_round["id"], participant["id"]),
                )
    finally:
        connection.close()


def test_check_constraints_reject_out_of_range_values(clean_database, db_dsn) -> None:
    connection = psycopg2.connect(db_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "UPDATE action_cards SET fee_rate = 1.5 WHERE code = 'salary'"
                )
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "UPDATE action_cards SET min_amount = max_amount + 1 WHERE code = 'salary'"
                )
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute("UPDATE rounds SET status = 'archived' WHERE id = 1")
    finally:
        connection.close()


def test_seeded_card_contract_matches_the_catalog(clean_database, db_dsn) -> None:
    from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG, build_parameter_schema

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT code, version, parameter_schema, min_amount, max_amount "
                "FROM action_cards ORDER BY id"
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    assert len(rows) == len(CARD_CATALOG)
    by_key = {(code, version): (schema, low, high) for code, version, schema, low, high in rows}
    for entry in CARD_CATALOG:
        schema, low, high = by_key[(entry["code"], entry["version"])]
        assert schema == build_parameter_schema(entry)
        assert Decimal(low) == entry["min_amount"]
        assert Decimal(high) == entry["max_amount"]


def test_seed_removes_an_obsolete_operation(clean_database, db_dsn) -> None:
    """Re-running the seed converges an existing database to the four-card catalog."""
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO action_cards (code, version, title, category, flow, "
                "risk_weight, energy_cost, time_cost, fee_rate, min_amount, "
                "max_amount, max_frequency, requires_card_code, parameter_schema, "
                "is_active, created_at) "
                "SELECT 'obsolete_operation', version, 'Старая операция', category, flow, "
                "risk_weight, energy_cost, time_cost, fee_rate, min_amount, "
                "max_amount, max_frequency, requires_card_code, parameter_schema, "
                "is_active, created_at FROM action_cards WHERE code = 'salary'"
            )
        connection.commit()
    finally:
        connection.close()

    environment = dict(os.environ)
    environment["DATABASE_URL"] = TEST_DATABASE_URL
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.seed_database"],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT code FROM action_cards ORDER BY code")
            codes = [row[0] for row in cursor.fetchall()]
    finally:
        connection.close()
    assert codes == ["card_transfer", "cash_deposit", "cash_withdrawal", "salary"]
