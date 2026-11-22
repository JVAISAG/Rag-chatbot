"""Enable pgvector for the workspace database.

Revision ID: 20261107_01
Revises: None
"""

from alembic import op


revision = "20261107_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")


def downgrade() -> None:
    # The extension may predate this migration or be used by other tables.
    pass
