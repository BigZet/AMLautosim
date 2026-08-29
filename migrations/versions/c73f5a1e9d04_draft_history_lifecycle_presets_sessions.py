"""draft history, round lifecycle, presets and session metadata

Adds, in one step, the four schema changes the workshop flow needs:

* `scenario_versions` — append-only history of every saved draft, plus the
  pointers on `scenarios` that say which version is current and which one was
  submitted;
* `round_presets` — reusable configurations an organiser prepares up front;
* the `stopped` round status together with `stopped_at`,
  `restarted_from_round_id` and `preset_id`;
* technical login metadata on `sessions` (IP, User-Agent, Accept-Language) and
  `users.first_login_at`.

Existing scenarios are backfilled with one version each so nothing that was
already saved loses its history.

Revision ID: c73f5a1e9d04
Revises: b1c4d7e93a20
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c73f5a1e9d04"
down_revision: str | None = "b1c4d7e93a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VARIANT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)
BIGINT_VARIANT = sa.Integer().with_variant(sa.BigInteger(), "postgresql")
IP_VARIANT = sa.String(length=45).with_variant(postgresql.INET(), "postgresql")


def upgrade() -> None:
    # ---- round presets ---------------------------------------------------
    op.create_table(
        "round_presets",
        sa.Column("id", BIGINT_VARIANT, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("game_config", JSON_VARIANT, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", BIGINT_VARIANT, nullable=False),
        sa.Column("updated_by_user_id", BIGINT_VARIANT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_round_presets_name"), "round_presets", ["name"], unique=True
    )
    op.create_check_constraint("ck_round_presets_revision", "round_presets", "revision >= 1")

    # ---- round lifecycle -------------------------------------------------
    op.add_column("rounds", sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "rounds", sa.Column("restarted_from_round_id", BIGINT_VARIANT, nullable=True)
    )
    op.add_column("rounds", sa.Column("preset_id", BIGINT_VARIANT, nullable=True))
    op.create_foreign_key(
        "fk_rounds_restarted_from", "rounds", "rounds", ["restarted_from_round_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_rounds_preset",
        "rounds",
        "round_presets",
        ["preset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("ck_rounds_status", "rounds", type_="check")
    op.create_check_constraint(
        "ck_rounds_status",
        "rounds",
        "status IN ('draft', 'active', 'stopped', 'scoring', 'completed')",
    )

    # ---- draft history ---------------------------------------------------
    op.create_table(
        "scenario_versions",
        sa.Column("id", BIGINT_VARIANT, autoincrement=True, nullable=False),
        sa.Column("scenario_id", BIGINT_VARIANT, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("steps", JSON_VARIANT, nullable=False),
        sa.Column("resource_snapshot", JSON_VARIANT, nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("restored_from_revision", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", BIGINT_VARIANT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_id", "revision", name="uq_scenario_versions_scenario_revision"
        ),
    )
    op.create_index(
        op.f("ix_scenario_versions_scenario_id"),
        "scenario_versions",
        ["scenario_id"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_scenario_versions_revision", "scenario_versions", "revision >= 1"
    )

    op.add_column("scenarios", sa.Column("current_version_id", BIGINT_VARIANT, nullable=True))
    op.add_column(
        "scenarios", sa.Column("submitted_version_id", BIGINT_VARIANT, nullable=True)
    )

    # Every scenario that already exists becomes the first entry of its own
    # history, so the version list is never empty for work done before this
    # migration.
    op.execute(
        """
        INSERT INTO scenario_versions (
            scenario_id, revision, label, steps, resource_snapshot,
            payload_hash, restored_from_revision, created_by_user_id, created_at
        )
        SELECT s.id, GREATEST(s.revision, 1), NULL, s.steps, s.resource_snapshot,
               s.payload_hash, NULL, s.participant_id, s.updated_at
        FROM scenarios s
        """
    )
    op.execute(
        """
        UPDATE scenarios s
        SET current_version_id = v.id,
            submitted_version_id = CASE
                WHEN s.status IN ('submitted', 'scored') THEN v.id ELSE NULL END
        FROM scenario_versions v
        WHERE v.scenario_id = s.id
        """
    )
    op.create_foreign_key(
        "fk_scenarios_current_version",
        "scenarios",
        "scenario_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_scenarios_submitted_version",
        "scenarios",
        "scenario_versions",
        ["submitted_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- session and login metadata --------------------------------------
    op.add_column("sessions", sa.Column("ip_address", IP_VARIANT, nullable=True))
    op.add_column("sessions", sa.Column("user_agent", sa.String(length=512), nullable=True))
    op.add_column(
        "sessions", sa.Column("accept_language", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "users", sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE users SET first_login_at = last_login_at WHERE last_login_at IS NOT NULL")
    op.execute(
        "CREATE INDEX ix_sessions_user_created ON sessions (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sessions_user_created")
    op.drop_column("users", "first_login_at")
    op.drop_column("sessions", "accept_language")
    op.drop_column("sessions", "user_agent")
    op.drop_column("sessions", "ip_address")

    op.drop_constraint("fk_scenarios_submitted_version", "scenarios", type_="foreignkey")
    op.drop_constraint("fk_scenarios_current_version", "scenarios", type_="foreignkey")
    op.drop_column("scenarios", "submitted_version_id")
    op.drop_column("scenarios", "current_version_id")
    op.drop_constraint(
        "ck_scenario_versions_revision", "scenario_versions", type_="check"
    )
    op.drop_index(op.f("ix_scenario_versions_scenario_id"), table_name="scenario_versions")
    op.drop_table("scenario_versions")

    op.drop_constraint("ck_rounds_status", "rounds", type_="check")
    op.create_check_constraint(
        "ck_rounds_status",
        "rounds",
        "status IN ('draft', 'active', 'scoring', 'completed')",
    )
    op.drop_constraint("fk_rounds_preset", "rounds", type_="foreignkey")
    op.drop_constraint("fk_rounds_restarted_from", "rounds", type_="foreignkey")
    op.drop_column("rounds", "preset_id")
    op.drop_column("rounds", "restarted_from_round_id")
    op.drop_column("rounds", "stopped_at")

    op.drop_constraint("ck_round_presets_revision", "round_presets", type_="check")
    op.drop_index(op.f("ix_round_presets_name"), table_name="round_presets")
    op.drop_table("round_presets")
