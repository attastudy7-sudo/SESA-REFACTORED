"""add phone to accounts

Revision ID: d94f80b3edcd
Revises: 0928baad00b7
Create Date: 2026-03-20 03:06:56.517034

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd94f80b3edcd'
down_revision = '0928baad00b7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_column('phone')
