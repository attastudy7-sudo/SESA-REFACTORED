"""add phone to accounts

Revision ID: d94f80b3edcd
Revises: 0928baad00b7
Create Date: 2026-03-20 03:06:56.517034

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'd94f80b3edcd'
down_revision = '0928baad00b7'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if not _column_exists('accounts', 'phone'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))


def downgrade():
    if _column_exists('accounts', 'phone'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.drop_column('phone')
