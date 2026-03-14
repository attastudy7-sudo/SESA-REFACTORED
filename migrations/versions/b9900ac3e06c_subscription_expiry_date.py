"""subscription expiry date

Revision ID: b9900ac3e06c
Revises: 4838ee558eeb
Create Date: 2026-03-13 00:04:31.489297

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'b9900ac3e06c'
down_revision = '4838ee558eeb'
branch_labels = None
depends_on = None


def column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.fetchone() is not None


def index_exists(name):
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :name"
    ), {"name": name})
    return result.fetchone() is not None


def upgrade():
    # Guarded — these may already exist if 4838ee558eeb ran on a fresh DB
    if not column_exists('school', 'subscription_expires'):
        op.add_column('school', sa.Column('subscription_expires', sa.DateTime(), nullable=True))
    if not index_exists('ix_school_subscription_expires'):
        op.create_index('ix_school_subscription_expires', 'school', ['subscription_expires'], unique=False)


def downgrade():
    if index_exists('ix_school_subscription_expires'):
        op.drop_index('ix_school_subscription_expires', table_name='school')
    if column_exists('school', 'subscription_expires'):
        op.drop_column('school', 'subscription_expires')