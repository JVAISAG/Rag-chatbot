"""Save revision-pinned comparison selections and editable research notes."""
from alembic import op
import sqlalchemy as sa

revision = '20261120_01'
down_revision = '20261115_06'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversations', sa.Column('source_ids', sa.JSON(), nullable=True))
    op.add_column('question_turns', sa.Column('timings', sa.JSON(), nullable=True))
    op.create_table('comparisons',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('collection_id', sa.Uuid(), sa.ForeignKey('collections.id', ondelete='SET NULL')),
        sa.Column('selections', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_comparisons_owner_id', 'comparisons', ['owner_id'])
    op.create_table('notes',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('collection_id', sa.Uuid(), sa.ForeignKey('collections.id', ondelete='SET NULL')),
        sa.Column('title', sa.Text(), nullable=False), sa.Column('markdown', sa.Text(), nullable=False),
        sa.Column('analysis_ids', sa.JSON(), nullable=False), sa.Column('comparison_ids', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_notes_owner_id', 'notes', ['owner_id'])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT 1 FROM notes UNION ALL SELECT 1 FROM comparisons LIMIT 1')).first():
        raise RuntimeError('Cannot downgrade while saved notes or comparisons exist.')
    op.drop_index('ix_notes_owner_id', table_name='notes')
    op.drop_table('notes')
    op.drop_index('ix_comparisons_owner_id', table_name='comparisons')
    op.drop_table('comparisons')
    op.drop_column('conversations', 'source_ids')
    op.drop_column('question_turns', 'timings')
