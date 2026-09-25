"""Durable scoring queue, leases and recoverable progress."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_scoring_jobs"
down_revision = "0003_auth_rate_limits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scoring_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "round_id", sa.BigInteger(), sa.ForeignKey("rounds.id", ondelete="SET NULL")
        ),
        sa.Column("original_round_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "actor_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("request_id", sa.String(128)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("owner", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("summary", JSONB()),
        sa.Column("error", JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('queued','running','completed','failed','cancelled')",
            name="ck_scoring_jobs_state",
        ),
        sa.CheckConstraint(
            "done >= 0 AND total >= done AND attempt >= 0",
            name="ck_scoring_jobs_progress",
        ),
    )
    op.create_index(
        "uq_scoring_jobs_active_round",
        "scoring_jobs",
        ["round_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued','running')"),
    )
    op.create_index(
        "ix_scoring_jobs_claim", "scoring_jobs", ["state", "lease_until", "created_at"]
    )


def downgrade():
    op.drop_table("scoring_jobs")
