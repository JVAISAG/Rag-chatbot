"""Retain source tags and reading progress across collections."""
from alembic import op
import sqlalchemy as sa

revision = '20261121_01'
down_revision = '20261120_01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sources', sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('sources', sa.Column('reading_status', sa.String(16), nullable=False, server_default='unread'))
    op.create_check_constraint('ck_sources_reading_status', 'sources', "reading_status IN ('unread', 'reading', 'read')")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM sources WHERE json_array_length(tags) > 0 OR reading_status <> 'unread' LIMIT 1")).first():
        raise RuntimeError('Cannot downgrade while saved source tags or reading progress exist.')
    op.drop_constraint('ck_sources_reading_status', 'sources', type_='check')
    op.drop_column('sources', 'reading_status')
    op.drop_column('sources', 'tags')
