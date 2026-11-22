"""Add searchable chunks and embedding-model metadata."""
from alembic import op
import sqlalchemy as sa
from src.workspace.vectors import Vector

revision = "20261113_01"
down_revision = "20261110_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("source_revisions", sa.Column("embedding_model", sa.Text(), nullable=True))
    op.create_table("chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("source_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.UniqueConstraint("revision_id", "ordinal", name="uq_chunks_revision_ordinal"))
    op.create_index("ix_chunks_revision_id", "chunks", ["revision_id"])


def downgrade():
    op.drop_index("ix_chunks_revision_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_column("source_revisions", "embedding_model")
