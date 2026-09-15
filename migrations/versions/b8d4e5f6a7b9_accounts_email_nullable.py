"""Make accounts.email nullable — students may register without an email.

The 0001_fresh_schema baseline created email as NOT NULL, but the Accounts
model declares it nullable and every student onboarding path (bulk upload of
students without emails, /join self-registration) inserts NULL. On Postgres
this raised NotNullViolation: 'null value in column "email"'.

Revision ID: b8d4e5f6a7b9
Revises: b7c4d9e1f2a3
Create Date: 2026-09-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'b8d4e5f6a7b9'
down_revision = 'b7c4d9e1f2a3'
branch_labels = None
depends_on = None


def _email_is_nullable():
    inspector = inspect(op.get_bind())
    for col in inspector.get_columns('accounts'):
        if col['name'] == 'email':
            return bool(col.get('nullable'))
    return True


def upgrade():
    if _email_is_nullable():
        return
    # batch_alter_table → plain ALTER COLUMN on Postgres, table rebuild on SQLite
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('email', existing_type=sa.String(length=120), nullable=True)


def downgrade():
    # Only re-apply NOT NULL when no NULL emails exist
    bind = op.get_bind()
    null_count = bind.execute(sa.text('SELECT COUNT(*) FROM accounts WHERE email IS NULL')).scalar()
    if null_count:
        raise RuntimeError(
            f'Cannot restore NOT NULL on accounts.email: {null_count} rows have NULL email.'
        )
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.alter_column('email', existing_type=sa.String(length=120), nullable=False)
