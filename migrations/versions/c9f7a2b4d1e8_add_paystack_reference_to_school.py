"""add paystack_reference and payment_date to school

Revision ID: c9f7a2b4d1e8
Revises: e570a2ba298a
Create Date: 2026-08-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c9f7a2b4d1e8'
down_revision = 'e570a2ba298a'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    school_cols = [col['name'] for col in inspector.get_columns('school')]
    with op.batch_alter_table('school', schema=None) as batch_op:
        if 'paystack_reference' not in school_cols:
            batch_op.add_column(sa.Column('paystack_reference', sa.String(length=100), nullable=True))
        if 'payment_date' not in school_cols:
            batch_op.add_column(sa.Column('payment_date', sa.DateTime(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    school_cols = [col['name'] for col in inspector.get_columns('school')]
    with op.batch_alter_table('school', schema=None) as batch_op:
        if 'payment_date' in school_cols:
            batch_op.drop_column('payment_date')
        if 'paystack_reference' in school_cols:
            batch_op.drop_column('paystack_reference')
