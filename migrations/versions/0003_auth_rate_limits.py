"""Shared authentication admission limits across API workers."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0003_auth_rate_limits'
down_revision = '0002_preserve_audit'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_rate_limits', sa.Column('key', sa.String(64), primary_key=True),
                    sa.Column('state', JSONB(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_auth_rate_limits_updated_at', 'auth_rate_limits', ['updated_at'])


def downgrade():
    op.drop_table('auth_rate_limits')
