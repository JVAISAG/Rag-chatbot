"""Add optional, user-editable source metadata."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_01"
down_revision = "20261114_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sources", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("authors", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("publication_date", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("sources", "publication_date")
    op.drop_column("sources", "authors")
    op.drop_column("sources", "title")
