"""subscription expiry date

Revision ID: b9900ac3e06c
Revises: 4838ee558eeb
Create Date: 2026-03-13 00:04:31.489297

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9900ac3e06c'
down_revision = '4838ee558eeb'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subscription_expires', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_school_subscription_expires'), ['subscription_expires'], unique=False)


def downgrade():
    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_school_subscription_expires'))
        batch_op.drop_column('subscription_expires')