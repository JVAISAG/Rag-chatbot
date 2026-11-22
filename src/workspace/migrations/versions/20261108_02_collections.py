"""Add account-owned research collections.

Revision ID: 20261108_02
Revises: 20261108_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261108_02"
down_revision = "20261108_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_collections_name_length"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_collections_name_nonempty"),
        sa.CheckConstraint("length(normalized_name) > 0", name="ck_collections_normalized_name"),
        sa.CheckConstraint("description IS NULL OR length(description) <= 2000", name="ck_collections_description_length"),
        sa.UniqueConstraint("owner_id", "normalized_name", name="uq_collections_owner_normalized_name"),
    )
    op.create_index("ix_collections_owner_created_at", "collections", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_collections_owner_created_at", table_name="collections")
    op.drop_table("collections")
