"""add consent fields to accounts

Revision ID: 0848ed5f0a10
Revises: 3b48be21bb6f
Create Date: 2026-03-20 14:37:44.429117

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0848ed5f0a10'
down_revision = '3b48be21bb6f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('consent_given', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('consent_given_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('consent_version', sa.String(length=10), nullable=True))

def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_column('consent_version')
        batch_op.drop_column('consent_given_at')
        batch_op.drop_column('consent_given')