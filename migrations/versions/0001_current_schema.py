"""Initial schema for the current single-use workshop game on PostgreSQL."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_current_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_cards",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("flow", sa.String(), nullable=False),
        sa.Column("risk_weight", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("energy_cost", sa.Integer(), nullable=False),
        sa.Column("time_cost", sa.Integer(), nullable=False),
        sa.Column("fee_rate", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("min_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("max_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("requires_card_code", sa.String(), nullable=True),
        sa.Column(
            "parameter_schema",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "energy_cost >= 0 AND time_cost >= 0", name="ck_action_cards_costs"
        ),
        sa.CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1", name="ck_action_cards_fee_rate"
        ),
        sa.CheckConstraint(
            "min_amount > 0 AND min_amount <= max_amount",
            name="ck_action_cards_amounts",
        ),
        sa.CheckConstraint(
            "requires_card_code IS NULL OR requires_card_code <> code",
            name="ck_action_cards_requires_other_card",
        ),
        sa.CheckConstraint("version > 0", name="ck_action_cards_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_action_cards_code_version"),
    )
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("blocked_reason", sa.String(length=500), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "blocked_by_user_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=True,
        ),
        sa.Column("access_revision", sa.Integer(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('participant', 'admin')", name="ck_users_role"),
        sa.CheckConstraint(
            "NOT is_blocked OR blocked_reason IS NOT NULL",
            name="ck_users_blocked_reason",
        ),
        sa.CheckConstraint(
            "failed_login_count >= 0", name="ck_users_failed_login_count"
        ),
        sa.ForeignKeyConstraint(
            ["blocked_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "rounds",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column(
            "game_config",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "scoring_summary",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scoring_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scoring_error",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'closed', 'scoring', 'completed')",
            name="ck_rounds_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rounds_status"), "rounds", ["status"], unique=False)
    op.create_index(
        "uq_rounds_single_game", "rounds", [sa.literal_column("(true)")], unique=True
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=False,
        ),
        sa.Column("session_id_hash", sa.String(length=64), nullable=False),
        sa.Column("audience", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=100), nullable=True),
        sa.Column(
            "revoked_by_user_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "audience IN ('play', 'admin')", name="ck_sessions_audience"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id_hash"),
    )
    op.create_index(
        op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_table(
        "scenarios",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "round_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "steps",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "resource_snapshot",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_client_mutation_id", sa.Uuid(), nullable=True),
        sa.Column("payload_hash", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('editing', 'submitted', 'scored')", name="ck_scenarios_status"
        ),
        sa.CheckConstraint("revision >= 0", name="ck_scenarios_revision"),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "round_id", "participant_id", name="uq_scenarios_round_id_participant_id"
        ),
    )
    op.create_index(
        "ix_scenarios_round_status", "scenarios", ["round_id", "status"], unique=False
    )
    op.create_index(op.f("ix_scenarios_status"), "scenarios", ["status"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "round_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "scenario_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["rounds.id"],
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_round_created",
        "audit_events",
        ["round_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "scoring_results",
        sa.Column(
            "id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "scenario_id",
            sa.Integer().with_variant(sa.BigInteger(), "postgresql"),
            nullable=False,
        ),
        sa.Column("risk_score", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("risk_label", sa.String(), nullable=False),
        sa.Column("stealth_score", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("resource_score", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("game_score", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "explanation",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("scoring_version", sa.String(), nullable=False),
        sa.Column("leaderboard_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "risk_label IN ('normal', 'review', 'suspicious')",
            name="ck_scoring_results_label",
        ),
        sa.CheckConstraint(
            "risk_score BETWEEN 0 AND 100 AND stealth_score BETWEEN 0 AND 100 AND resource_score BETWEEN 0 AND 100 AND game_score BETWEEN 0 AND 100",
            name="ck_scoring_results_ranges",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario_id", name="uq_scoring_results_scenario_id"),
    )


def downgrade() -> None:
    op.drop_table("scoring_results")
    op.drop_table("audit_events")
    op.drop_table("scenarios")
    op.drop_table("sessions")
    op.drop_table("rounds")
    op.drop_table("users")
    op.drop_table("action_cards")
