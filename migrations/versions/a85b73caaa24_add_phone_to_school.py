"""add phone to school

Revision ID: a85b73caaa24
Revises: 0001_fresh_schema
Create Date: 2026-03-20 00:24:34.421428

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'a85b73caaa24'
down_revision = '0001_fresh_schema'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if not _column_exists('school', 'phone'):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))


def downgrade():
    if _column_exists('school', 'phone'):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.drop_column('phone')
