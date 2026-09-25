"""Preserve audit when referenced game data is removed."""

from alembic import op

revision = "0002_preserve_audit"
down_revision = "0001_current_schema"
branch_labels = None
depends_on = None


def _replace(ondelete):
    for column, target in (("round_id", "rounds"), ("scenario_id", "scenarios")):
        name = f"audit_events_{column}_fkey"
        op.drop_constraint(name, "audit_events", type_="foreignkey")
        op.create_foreign_key(name, "audit_events", target, [column], ["id"], ondelete=ondelete)


def upgrade():
    _replace("SET NULL")


def downgrade():
    _replace(None)
