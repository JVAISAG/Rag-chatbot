"""Stage replacements separately and retain original revision file details."""
from alembic import op
import sqlalchemy as sa

revision = "20261115_03"
down_revision = "20261115_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("source_revisions", sa.Column("filename", sa.Text(), nullable=True))
    op.add_column("source_revisions", sa.Column("storage_key", sa.Text(), nullable=True))
    op.add_column("source_revisions", sa.Column("content_hash", sa.String(64), nullable=True))
    op.execute("""UPDATE source_revisions SET filename = sources.filename, storage_key = sources.storage_key,
                  content_hash = sources.content_hash FROM sources WHERE source_revisions.source_id = sources.id""")
    op.create_table("source_replacements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extract_job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("index_job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), unique=True),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("source_revisions.id", ondelete="SET NULL"), unique=True),
        sa.Column("filename", sa.Text(), nullable=False), sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="staged"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('staged', 'published', 'abandoned')", name="ck_source_replacements_status"))
    op.create_index("ix_source_replacements_source_id", "source_replacements", ["source_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM source_replacements LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while replacement records exist.")
    op.drop_index("ix_source_replacements_source_id", table_name="source_replacements")
    op.drop_table("source_replacements")
    for column in ("content_hash", "storage_key", "filename"):
        op.drop_column("source_revisions", column)
