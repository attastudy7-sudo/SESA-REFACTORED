"""add consent fields to accounts

Revision ID: 0848ed5f0a10
Revises: 3b48be21bb6f
Create Date: 2026-03-20 14:37:44.429117

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '0848ed5f0a10'
down_revision = '3b48be21bb6f'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        if not _column_exists('accounts', 'consent_given'):
            batch_op.add_column(sa.Column('consent_given', sa.Boolean(), server_default='0', nullable=False))
        if not _column_exists('accounts', 'consent_given_at'):
            batch_op.add_column(sa.Column('consent_given_at', sa.DateTime(), nullable=True))
        if not _column_exists('accounts', 'consent_version'):
            batch_op.add_column(sa.Column('consent_version', sa.String(length=10), nullable=True))

def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        if _column_exists('accounts', 'consent_version'):
            batch_op.drop_column('consent_version')
        if _column_exists('accounts', 'consent_given_at'):
            batch_op.drop_column('consent_given_at')
        if _column_exists('accounts', 'consent_given'):
            batch_op.drop_column('consent_given')
