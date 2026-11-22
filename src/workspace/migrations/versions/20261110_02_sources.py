"""Private uploaded sources and extracted revisions."""
from alembic import op
import sqlalchemy as sa

revision = "20261110_02"
down_revision = "20261110_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_sources_owner_hash"))
    op.create_table("source_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("extraction_version", sa.String(32), nullable=False))
    op.create_table("collection_sources",
        sa.Column("collection_id", sa.Uuid(), sa.ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True))


def downgrade():
    op.drop_table("collection_sources")
    op.drop_table("source_revisions")
    op.drop_table("sources")
