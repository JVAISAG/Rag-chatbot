"""Persist private conversations and evidence-backed question turns."""
from alembic import op
import sqlalchemy as sa
revision = "20261114_01"
down_revision = "20261113_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection_id", sa.Uuid(), sa.ForeignKey("collections.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_conversations_owner_id", "conversations", ["owner_id"])
    op.create_table("question_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("request_key", sa.Uuid()),
        sa.Column("retrieval_query", sa.Text()), sa.Column("answer", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("evidence", sa.JSON()), sa.Column("model", sa.Text()),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default="qa-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "request_key", name="uq_question_turn_request_key"))
    op.create_index("ix_question_turns_conversation_id", "question_turns", ["conversation_id"])


def downgrade():
    op.drop_index("ix_question_turns_conversation_id", table_name="question_turns")
    op.drop_table("question_turns")
    op.drop_index("ix_conversations_owner_id", table_name="conversations")
    op.drop_table("conversations")
