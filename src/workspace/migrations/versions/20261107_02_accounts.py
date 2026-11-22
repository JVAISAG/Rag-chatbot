"""Create account, identifier, and session tables.

Revision ID: 20261107_02
Revises: 20261107_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261107_02"
down_revision = "20261107_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "user_identifiers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('email', 'username')", name="ck_user_identifiers_kind"),
        sa.CheckConstraint("length(trim(value)) > 0", name="ck_user_identifiers_value"),
        sa.CheckConstraint("length(trim(normalized_value)) > 0", name="ck_user_identifiers_normalized_value"),
        sa.UniqueConstraint("normalized_value", name="uq_user_identifiers_normalized_value"),
        sa.UniqueConstraint("user_id", "kind", name="uq_user_identifiers_user_kind"),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("user_identifiers")
    op.drop_table("users")
