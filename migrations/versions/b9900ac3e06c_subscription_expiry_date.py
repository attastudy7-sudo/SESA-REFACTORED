"""subscription expiry date

Revision ID: b9900ac3e06c
Revises: 4838ee558eeb
Create Date: 2026-03-13 00:04:31.489297

"""
from alembic import op
import sqlalchemy as sa


revision = 'b9900ac3e06c'
down_revision = '4838ee558eeb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('school', sa.Column('subscription_expires', sa.DateTime(), nullable=True))
    op.create_index('ix_school_subscription_expires', 'school', ['subscription_expires'], unique=False)


def downgrade():
    op.drop_index('ix_school_subscription_expires', table_name='school')
    op.drop_column('school', 'subscription_expires')
