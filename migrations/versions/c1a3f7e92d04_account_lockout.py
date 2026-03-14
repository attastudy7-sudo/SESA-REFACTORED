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
from sqlalchemy import text

revision = 'c1a3f7e92d04'
down_revision = 'b9900ac3e06c'
branch_labels = None
depends_on = None


def column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.fetchone() is not None


def upgrade():
    # accounts — guarded in case a prior migration already added these
    if not column_exists('accounts', 'failed_attempts'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.add_column(sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'))
    if not column_exists('accounts', 'locked_until'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))

    # school — guarded in case 4838ee558eeb already added these
    if not column_exists('school', 'failed_attempts'):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.add_column(sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'))
    if not column_exists('school', 'locked_until'):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))


def downgrade():
    if column_exists('school', 'locked_until'):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.drop_column('locked_until')
    if column_exists('school', 'failed_attempts'):
        with op.batch_alter_table('school', schema=None) as batch_op:
            batch_op.drop_column('failed_attempts')

    if column_exists('accounts', 'locked_until'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.drop_column('locked_until')
    if column_exists('accounts', 'failed_attempts'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.drop_column('failed_attempts')