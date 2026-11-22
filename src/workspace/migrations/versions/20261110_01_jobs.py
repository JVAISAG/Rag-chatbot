"""Create durable background jobs.

Revision ID: 20261110_01
Revises: 20261108_02
"""

from alembic import op
import sqlalchemy as sa

revision = "20261110_01"
down_revision = "20261108_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_jobs_status"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts", name="ck_jobs_attempts"),
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_table("jobs")
