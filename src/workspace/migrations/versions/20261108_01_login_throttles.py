"""Store persistent login-throttling counters.

Revision ID: 20261108_01
Revises: 20261107_02
"""

from alembic import op
import sqlalchemy as sa


revision = "20261108_01"
down_revision = "20261107_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_throttles",
        sa.Column("scope", sa.String(8), primary_key=True),
        sa.Column("key_digest", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('account', 'unknown', 'client')", name="ck_login_throttles_scope"),
        sa.CheckConstraint("length(key_digest) = 64", name="ck_login_throttles_key_digest"),
        sa.CheckConstraint("attempts >= 0", name="ck_login_throttles_attempts"),
    )
    op.create_index("ix_login_throttles_updated_at", "login_throttles", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_login_throttles_updated_at", table_name="login_throttles")
    op.drop_table("login_throttles")
