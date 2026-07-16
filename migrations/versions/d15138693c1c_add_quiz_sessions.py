"""add_quiz_sessions

Revision ID: d15138693c1c
Revises: d94f80b3edcd
Create Date: 2026-03-20 03:24:16.941033

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'd15138693c1c'
down_revision = 'd94f80b3edcd'
branch_labels = None
depends_on = None


def _table_exists(name):
    return name in inspect(op.get_bind()).get_table_names()


def _index_exists(name):
    inspector = inspect(op.get_bind())
    for table in inspector.get_table_names():
        for idx in inspector.get_indexes(table):
            if idx['name'] == name:
                return True
    return False


def upgrade():
    if not _table_exists('quiz_sessions'):
        op.create_table('quiz_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('test_type', sa.String(length=100), nullable=False),
        sa.Column('q_index', sa.Integer(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('answers', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'test_type', name='uq_quiz_user_test')
        )
    if not _index_exists('ix_quiz_sessions_expires_at'):
        with op.batch_alter_table('quiz_sessions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quiz_sessions_expires_at'), ['expires_at'], unique=False)
    if not _index_exists('ix_quiz_sessions_test_type'):
        with op.batch_alter_table('quiz_sessions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quiz_sessions_test_type'), ['test_type'], unique=False)
    if not _index_exists('ix_quiz_sessions_user_id'):
        with op.batch_alter_table('quiz_sessions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_quiz_sessions_user_id'), ['user_id'], unique=False)

    inspector = inspect(op.get_bind())
    upload_col = next((c for c in inspector.get_columns('school') if c['name'] == 'upload_enabled'), None)
    if upload_col and not upload_col.get('nullable', True):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.alter_column('upload_enabled',
                   existing_type=sa.BOOLEAN(),
                   nullable=True,
                   existing_server_default=sa.text('false'))


def downgrade():
    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.alter_column('upload_enabled',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))

    with op.batch_alter_table('quiz_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_quiz_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_quiz_sessions_test_type'))
        batch_op.drop_index(batch_op.f('ix_quiz_sessions_expires_at'))

    op.drop_table('quiz_sessions')
