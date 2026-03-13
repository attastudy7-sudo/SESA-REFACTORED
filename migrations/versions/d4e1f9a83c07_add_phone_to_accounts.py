"""Add phone field to accounts for SMS alerts.

Revision ID: d4e1f9a83c07
Revises: c1a3f7e92d04
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e1f9a83c07'
down_revision = 'c1a3f7e92d04'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_column('phone')