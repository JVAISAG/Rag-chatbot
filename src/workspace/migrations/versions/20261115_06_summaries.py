"""Persist revision-pinned summaries and resumable analysis checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = '20261115_06'
down_revision = '20261115_05'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('analyses',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('sources.id', ondelete='SET NULL')),
        sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('source_revisions.id', ondelete='SET NULL')),
        sa.Column('job_id', sa.Uuid(), sa.ForeignKey('jobs.id'), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('state', sa.JSON(), nullable=False), sa.Column('result', sa.JSON()),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('prompt_version', sa.String(32), nullable=False, server_default='summary-v1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_analyses_owner_id', 'analyses', ['owner_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM analyses LIMIT 1')).first():
        raise RuntimeError('Cannot downgrade while saved analyses exist.')
    op.drop_index('ix_analyses_owner_id', table_name='analyses')
    op.drop_table('analyses')
