"""Preserve the URL associated with a staged article refresh."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_05"
down_revision = "20261115_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("source_replacements", sa.Column("original_url", sa.Text(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM source_replacements WHERE original_url IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while article refresh records exist.")
    op.drop_column("source_replacements", "original_url")
