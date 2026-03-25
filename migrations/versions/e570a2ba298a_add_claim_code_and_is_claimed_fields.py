"""add claim code and is_claimed fields

Revision ID: e570a2ba298a
Revises: 63d965640fb8
Create Date: 2026-03-24 19:40:27.962078

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e570a2ba298a'
down_revision = '63d965640fb8'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── accounts ─────────────────────────────────────────────────────────────
    acct_cols = [col['name'] for col in inspector.get_columns('accounts')]
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        if 'claim_code_hash' not in acct_cols:
            batch_op.add_column(sa.Column('claim_code_hash', sa.String(length=256), nullable=True))
        if 'claim_code_plain' not in acct_cols:
            batch_op.add_column(sa.Column('claim_code_plain', sa.String(length=20), nullable=True))
        if 'is_claimed' not in acct_cols:
            batch_op.add_column(sa.Column('is_claimed', sa.Boolean(), nullable=False,
                                          server_default='1'))

    # NOTE: test_results foreign key block intentionally omitted.
    # SQLite cannot drop/recreate unnamed foreign keys via batch mode.
    # The existing FK (accounts.id, ondelete=CASCADE) is already correct in the model.


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    acct_cols = [col['name'] for col in inspector.get_columns('accounts')]
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        if 'is_claimed' in acct_cols:
            batch_op.drop_column('is_claimed')
        if 'claim_code_plain' in acct_cols:
            batch_op.drop_column('claim_code_plain')
        if 'claim_code_hash' in acct_cols:
            batch_op.drop_column('claim_code_hash')