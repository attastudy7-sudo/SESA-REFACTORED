"""subscription expiry date

Revision ID: b9900ac3e06c
Revises: 4838ee558eeb
Create Date: 2026-03-13 00:04:31.489297

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'b9900ac3e06c'
down_revision = '4838ee558eeb'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def _index_exists(name):
    inspector = inspect(op.get_bind())
    for table in inspector.get_table_names():
        for idx in inspector.get_indexes(table):
            if idx['name'] == name:
                return True
    return False


def upgrade():
    if not _column_exists('school', 'subscription_expires'):
        op.add_column('school', sa.Column('subscription_expires', sa.DateTime(), nullable=True))
    if not _index_exists('ix_school_subscription_expires'):
        op.create_index('ix_school_subscription_expires', 'school', ['subscription_expires'], unique=False)


def downgrade():
    if _index_exists('ix_school_subscription_expires'):
        op.drop_index('ix_school_subscription_expires', table_name='school')
    if _column_exists('school', 'subscription_expires'):
        op.drop_column('school', 'subscription_expires')
