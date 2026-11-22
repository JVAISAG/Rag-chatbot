"""Record original article addresses on sources and their revisions."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_04"
down_revision = "20261115_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sources", sa.Column("original_url", sa.Text(), nullable=True))
    op.add_column("source_revisions", sa.Column("original_url", sa.Text(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM sources WHERE original_url IS NOT NULL UNION ALL SELECT 1 FROM source_revisions WHERE original_url IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while article URLs are stored.")
    op.drop_column("source_revisions", "original_url")
    op.drop_column("sources", "original_url")
