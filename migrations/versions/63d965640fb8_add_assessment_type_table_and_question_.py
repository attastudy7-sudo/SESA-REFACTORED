"""add assessment_type table and question order

Revision ID: 63d965640fb8
Revises: 0e25bd077c0c
Create Date: 2026-03-22 19:46:23.346535

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '63d965640fb8'
down_revision = '0e25bd077c0c'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if not _column_exists('question', 'order'):
        with op.batch_alter_table('question', schema=None) as batch_op:
            batch_op.add_column(sa.Column('order', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'accounts', ['user_id'], ['id'])

    if _column_exists('question', 'order'):
        with op.batch_alter_table('question', schema=None) as batch_op:
            batch_op.drop_column('order')

    with op.batch_alter_table('counsellor_profiles', schema=None) as batch_op:
        batch_op.alter_column('ghana_card_number',
               existing_type=sa.String(length=500),
               type_=sa.VARCHAR(length=30),
               existing_nullable=True)

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.alter_column('email',
               existing_type=sa.VARCHAR(length=120),
               nullable=False)

    op.drop_table('assessment_type')
