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

revision = 'c1a3f7e92d04'
down_revision = 'b9900ac3e06c'
branch_labels = None
depends_on = None


def upgrade():
    # ── accounts ─────────────────────────────────────────────────────────────
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('locked_until', sa.DateTime(), nullable=True)
        )

    # ── school ────────────────────────────────────────────────────────────────
    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('locked_until', sa.DateTime(), nullable=True)
        )


def do
wngrade():
    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_attempts')

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_attempts')