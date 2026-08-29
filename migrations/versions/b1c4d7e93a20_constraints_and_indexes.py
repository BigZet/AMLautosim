"""constraints and indexes from docs/data-model.md

Adds the invariants PostgreSQL must enforce itself: at most one active/scoring
round, value ranges for money and scores, and the query indexes the round and
leaderboard reads rely on.

Revision ID: b1c4d7e93a20
Revises: 2988b0ed1f98
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b1c4d7e93a20"
down_revision: str | None = "2988b0ed1f98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- enumerations -----------------------------------------------------
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('participant', 'admin')"
    )
    op.create_check_constraint(
        "ck_users_failed_login_count", "users", "failed_login_count >= 0"
    )
    op.create_check_constraint(
        "ck_users_blocked_reason",
        "users",
        "(is_blocked = false) OR (blocked_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_rounds_status",
        "rounds",
        "status IN ('draft', 'active', 'scoring', 'completed')",
    )
    op.create_check_constraint(
        "ck_scenarios_status",
        "scenarios",
        "status IN ('draft', 'submitted', 'scored')",
    )
    op.create_check_constraint("ck_scenarios_revision", "scenarios", "revision >= 0")
    op.create_check_constraint(
        "ck_sessions_audience", "sessions", "audience IN ('play', 'admin')"
    )

    # --- action card value ranges ----------------------------------------
    op.create_check_constraint("ck_action_cards_version", "action_cards", "version > 0")
    op.create_check_constraint(
        "ck_action_cards_costs",
        "action_cards",
        "energy_cost >= 0 AND time_cost >= 0 AND trust_cost >= 0",
    )
    op.create_check_constraint(
        "ck_action_cards_amounts",
        "action_cards",
        "min_amount > 0 AND min_amount <= max_amount",
    )
    op.create_check_constraint(
        "ck_action_cards_fee_rate", "action_cards", "fee_rate >= 0 AND fee_rate <= 1"
    )
    op.create_check_constraint(
        "ck_action_cards_max_frequency", "action_cards", "max_frequency >= 1"
    )
    op.create_check_constraint(
        "ck_action_cards_requires_other_card",
        "action_cards",
        "requires_card_code IS NULL OR requires_card_code <> code",
    )

    # --- result and adjustment ranges ------------------------------------
    op.create_check_constraint(
        "ck_scoring_results_ranges",
        "scoring_results",
        "risk_score BETWEEN 0 AND 100 AND stealth_score BETWEEN 0 AND 100 "
        "AND resource_score BETWEEN 0 AND 100 AND game_score BETWEEN 0 AND 100",
    )
    op.create_check_constraint(
        "ck_scoring_results_label",
        "scoring_results",
        "risk_label IN ('normal', 'review', 'suspicious')",
    )
    op.create_check_constraint(
        "ck_leaderboard_adjustments_ranges",
        "leaderboard_adjustments",
        "(risk_score_override IS NULL OR risk_score_override BETWEEN 0 AND 100) "
        "AND (resource_score_override IS NULL OR resource_score_override BETWEEN 0 AND 100) "
        "AND (game_score_override IS NULL OR game_score_override BETWEEN 0 AND 100)",
    )
    op.create_check_constraint(
        "ck_leaderboard_adjustments_any_override",
        "leaderboard_adjustments",
        "risk_score_override IS NOT NULL OR resource_score_override IS NOT NULL "
        "OR game_score_override IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_leaderboard_adjustments_revision", "leaderboard_adjustments", "revision >= 1"
    )

    # --- single active round ---------------------------------------------
    op.execute(
        "CREATE UNIQUE INDEX uq_rounds_single_active ON rounds ((1)) "
        "WHERE status IN ('active', 'scoring')"
    )

    # --- query indexes ----------------------------------------------------
    op.execute(
        "CREATE INDEX ix_users_blocked ON users (id) WHERE is_blocked = true"
    )
    op.create_index("ix_rounds_status_created_at", "rounds", ["status", "created_at"])
    op.create_index("ix_scenarios_round_status", "scenarios", ["round_id", "status"])
    op.execute(
        "CREATE INDEX ix_scenarios_participant_updated "
        "ON scenarios (participant_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_scoring_results_board "
        "ON scoring_results (game_score DESC, risk_score ASC)"
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.execute(
        "CREATE INDEX ix_audit_events_round_created "
        "ON audit_events (round_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_events_actor_created "
        "ON audit_events (actor_user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_events_scenario_created "
        "ON audit_events (scenario_id, created_at DESC)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_audit_events_idempotency ON audit_events "
        "(actor_user_id, event_type, target_type, target_id, idempotency_key_hash) "
        "WHERE idempotency_key_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_audit_events_idempotency")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_scenario_created")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_actor_created")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_round_created")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.execute("DROP INDEX IF EXISTS ix_scoring_results_board")
    op.execute("DROP INDEX IF EXISTS ix_scenarios_participant_updated")
    op.drop_index("ix_scenarios_round_status", table_name="scenarios")
    op.drop_index("ix_rounds_status_created_at", table_name="rounds")
    op.execute("DROP INDEX IF EXISTS ix_users_blocked")
    op.execute("DROP INDEX IF EXISTS uq_rounds_single_active")

    op.drop_constraint(
        "ck_leaderboard_adjustments_revision", "leaderboard_adjustments", type_="check"
    )
    op.drop_constraint(
        "ck_leaderboard_adjustments_any_override", "leaderboard_adjustments", type_="check"
    )
    op.drop_constraint(
        "ck_leaderboard_adjustments_ranges", "leaderboard_adjustments", type_="check"
    )
    op.drop_constraint("ck_scoring_results_label", "scoring_results", type_="check")
    op.drop_constraint("ck_scoring_results_ranges", "scoring_results", type_="check")
    op.drop_constraint(
        "ck_action_cards_requires_other_card", "action_cards", type_="check"
    )
    op.drop_constraint("ck_action_cards_max_frequency", "action_cards", type_="check")
    op.drop_constraint("ck_action_cards_fee_rate", "action_cards", type_="check")
    op.drop_constraint("ck_action_cards_amounts", "action_cards", type_="check")
    op.drop_constraint("ck_action_cards_costs", "action_cards", type_="check")
    op.drop_constraint("ck_action_cards_version", "action_cards", type_="check")
    op.drop_constraint("ck_sessions_audience", "sessions", type_="check")
    op.drop_constraint("ck_scenarios_revision", "scenarios", type_="check")
    op.drop_constraint("ck_scenarios_status", "scenarios", type_="check")
    op.drop_constraint("ck_rounds_status", "rounds", type_="check")
    op.drop_constraint("ck_users_blocked_reason", "users", type_="check")
    op.drop_constraint("ck_users_failed_login_count", "users", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
