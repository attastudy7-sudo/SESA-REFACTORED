"""add_counsellor_profiles

Revision ID: 3b48be21bb6f
Revises: d15138693c1c
Create Date: 2026-03-20 04:24:23.206757

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3b48be21bb6f'
down_revision = 'd15138693c1c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('counsellor_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('gpc_number', sa.String(length=50), nullable=True),
    sa.Column('gacc_number', sa.String(length=50), nullable=True),
    sa.Column('ghana_card_number', sa.String(length=30), nullable=True),
    sa.Column('specialisations', sa.String(length=300), nullable=True),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('years_experience', sa.Integer(), nullable=True),
    sa.Column('photo_url', sa.String(length=500), nullable=True),
    sa.Column('verification_status', sa.String(length=20), nullable=False),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=False),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('subscription_paid', sa.Boolean(), nullable=False),
    sa.Column('subscription_expires', sa.DateTime(), nullable=True),
    sa.Column('paystack_reference', sa.String(length=100), nullable=True),
    sa.Column('payment_date', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('counsellor_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_counsellor_profiles_account_id'), ['account_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_counsellor_profiles_verification_status'), ['verification_status'], unique=False)


def downgrade():
    with op.batch_alter_table('counsellor_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_counsellor_profiles_verification_status'))
        batch_op.drop_index(batch_op.f('ix_counsellor_profiles_account_id'))

    op.drop_table('counsellor_profiles')