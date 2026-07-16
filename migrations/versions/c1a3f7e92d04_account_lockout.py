"""Account and school admin lockout after failed logins.

Revision ID: c1a3f7e92d04
Revises: b9900ac3e06c
Create Date: 2026-03-13

Adds:
  accounts.failed_attempts  INTEGER NOT NULL DEFAULT 0
  accounts.locked_until     DATETIME NULL
  school.failed_attempts    INTEGER NOT NULL DEFAULT 0
  school.locked_until       DATETIME NULL
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'c1a3f7e92d04'
down_revision = 'b9900ac3e06c'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade():
    # accounts
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        if not _column_exists('accounts', 'failed_attempts'):
            batch_op.add_column(
                sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0')
            )
        if not _column_exists('accounts', 'locked_until'):
            batch_op.add_column(
                sa.Column('locked_until', sa.DateTime(), nullable=True)
            )

    # school
    with op.batch_alter_table('school', schema=None) as batch_op:
        if not _column_exists('school', 'failed_attempts'):
            batch_op.add_column(
                sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0')
            )
        if not _column_exists('school', 'locked_until'):
            batch_op.add_column(
                sa.Column('locked_until', sa.DateTime(), nullable=True)
            )


def downgrade():
    with op.batch_alter_table('school', schema=None) as batch_op:
        if _column_exists('school', 'locked_until'):
            batch_op.drop_column('locked_until')
        if _column_exists('school', 'failed_attempts'):
            batch_op.drop_column('failed_attempts')

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        if _column_exists('accounts', 'locked_until'):
            batch_op.drop_column('locked_until')
        if _column_exists('accounts', 'failed_attempts'):
            batch_op.drop_column('failed_attempts')
