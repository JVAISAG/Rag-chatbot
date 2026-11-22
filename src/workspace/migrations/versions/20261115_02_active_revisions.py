"""Allow retained revisions and select a source's searchable revision."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_02"
down_revision = "20261115_01"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("source_revisions_source_id_key", "source_revisions", type_="unique")
    op.add_column("sources", sa.Column("active_revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_sources_active_revision_id", "sources", "source_revisions",
                          ["active_revision_id"], ["id"], ondelete="SET NULL")
    op.execute("""UPDATE sources SET active_revision_id = source_revisions.id
               FROM source_revisions WHERE source_revisions.source_id = sources.id
               AND source_revisions.embedding_model IS NOT NULL""")


def downgrade():
    # Do not discard historical revisions to satisfy the old uniqueness rule.
    duplicates = op.get_bind().execute(sa.text("""SELECT 1 FROM source_revisions
        GROUP BY source_id HAVING COUNT(*) > 1 LIMIT 1""")).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade while a source has multiple revisions.")
    op.drop_constraint("fk_sources_active_revision_id", "sources", type_="foreignkey")
    op.drop_column("sources", "active_revision_id")
    op.create_unique_constraint("source_revisions_source_id_key", "source_revisions", ["source_id"])
