"""Upgrade populated legacy storage without retaining retired resource rules."""

import os
import subprocess
import sys
import uuid
from copy import deepcopy

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import Json

from src.aml_workshop_simulator.domain.rules import REFERENCE_GAME_CONFIG
from src.aml_workshop_simulator.schemas.round_config import GameConfigIn
from tests.conftest import ADMIN_DSN, ROOT, TEST_DATABASE_URL


def test_upgrade_populated_resource_data() -> None:
    scratch = f"aml_resource_migrate_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(ADMIN_DSN)
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(scratch)))
    finally:
        admin.close()

    environment = dict(os.environ)
    environment["DATABASE_URL"] = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/" + scratch
    dsn = environment["DATABASE_URL"].replace("+asyncpg", "")

    def upgrade(revision):
        completed = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
        )
        assert completed.returncode == 0, completed.stderr

    try:
        upgrade("c73f5a1e9d04")
        config = deepcopy(REFERENCE_GAME_CONFIG)
        config["schema_version"] = 3
        config["ruleset_version"] = "game-rules-v2"
        config["config_version"] = "legacy-hash"
        config["resources"]["initial_trust"] = 100
        config["operations"][0]["trust_cost"] = 4
        config["leaderboard"]["version"] = "leaderboard-v1"
        config["leaderboard"]["resource_weights"] = {
            "balance": "0.20", "energy": "0.15", "time": "0.15",
            "trust": "0.25", "fees": "0.15", "slots": "0.10",
        }
        snapshot = {
            "schema_version": 3, "ruleset_version": "game-rules-v2",
            "valid": False,
            "resources_after": {"balance": "250000.00", "energy": 12, "time": 15,
                                "trust": -1, "slots": 7},
            "violations": [{"reason": "insufficient_trust"}],
            "per_step": [{"trust_cost": 101, "trust_after": -1,
                          "resources_before": {"energy": 14, "trust": 100},
                          "resources_after": {"energy": 12, "trust": -1}}],
        }
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (email, hashed_password, role, is_blocked, "
                "access_revision, failed_login_count) "
                "VALUES ('legacy@example.com', 'unused', 'admin', false, 1, 0)"
            )
            cursor.execute(
                "INSERT INTO rounds (title, status, config_revision, game_config, "
                "created_by_user_id, created_at) VALUES ('Legacy', 'active', 3, %s, 1, now())",
                (Json(config),),
            )
            cursor.execute(
                "INSERT INTO round_presets (name, game_config, revision, created_by_user_id, "
                "updated_by_user_id, created_at, updated_at) "
                "VALUES ('Legacy preset', %s, 2, 1, 1, now(), now())", (Json(config),),
            )
            cursor.execute(
                "INSERT INTO scenarios (round_id, participant_id, status, steps, "
                "resource_snapshot, revision, updated_at) "
                "VALUES (1, 1, 'draft', '[]', %s, 1, now())", (Json(snapshot),),
            )
            cursor.execute(
                "INSERT INTO scenario_versions (scenario_id, revision, steps, "
                "resource_snapshot, created_by_user_id, created_at) "
                "VALUES (1, 1, '[]', %s, 1, now())", (Json(snapshot),),
            )
            cursor.execute(
                "INSERT INTO action_cards (code, version, title, category, flow, risk_weight, "
                "energy_cost, time_cost, trust_cost, fee_rate, min_amount, max_amount, "
                "max_frequency, parameter_schema, is_active, created_at) "
                "VALUES ('legacy', 1, 'Legacy', 'Legacy', 'credit', 1, 1, 1, 5, 0, 1, 100, "
                "1, %s, true, now())",
                (Json({"fields": [{"options": [{"trust_cost": 4, "risk_points": 8}]}]}),),
            )

        upgrade("head")
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT game_config, config_revision FROM rounds")
            migrated, revision = cursor.fetchone()
            GameConfigIn.model_validate(migrated)
            assert revision == 4
            assert migrated["leaderboard"] == REFERENCE_GAME_CONFIG["leaderboard"]
            assert migrated["config_version"].startswith("round-config-v4:sha256:")
            cursor.execute("SELECT game_config, revision FROM round_presets")
            preset, revision = cursor.fetchone()
            assert preset == migrated
            assert revision == 3
            for table in ("scenarios", "scenario_versions"):
                cursor.execute(sql.SQL("SELECT resource_snapshot FROM {}").format(sql.Identifier(table)))
                result = cursor.fetchone()[0]
                assert result["valid"] is True
                assert result["violations"] == []
                assert result["resources_after"]["available_steps"] == 7
                assert result["per_step"] == [{
                    "resources_before": {"energy": 14}, "resources_after": {"energy": 12},
                }]
                assert "trust" not in result["resources_after"]
            cursor.execute("SELECT parameter_schema FROM action_cards")
            assert cursor.fetchone()[0] == {"fields": [{"options": [{"risk_points": 8}]}]}
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'action_cards' AND column_name = 'trust_cost'"
            )
            assert cursor.fetchone() is None
    finally:
        admin = psycopg2.connect(ADMIN_DSN)
        admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch))
                )
        finally:
            admin.close()
