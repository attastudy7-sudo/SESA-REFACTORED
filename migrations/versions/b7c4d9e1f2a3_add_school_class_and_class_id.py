"""add school_class table and class_id to accounts

Revision ID: b7c4d9e1f2a3
Revises: c9f7a2b4d1e8
Create Date: 2026-08-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'b7c4d9e1f2a3'
down_revision = 'c9f7a2b4d1e8'
branch_labels = None
depends_on = None


def _table_exists(name):
    names = inspect(op.get_bind()).get_table_names()
    if names and isinstance(names[0], tuple):
        names = [t[0] for t in names]
    return name in names


def _column_exists(table, column):
    return column in [c['name'] for c in inspect(op.get_bind()).get_columns(table)]


def upgrade():
    if not _table_exists('school_class'):
        op.create_table(
            'school_class',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('school_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('level', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['school_id'], ['school.id'], name='fk_school_class_school_id'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('school_id', 'name', name='uq_school_class_school_name'),
        )

    if not _column_exists('accounts', 'class_id'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.add_column(sa.Column('class_id', sa.Integer(), nullable=True))

    # ── Backfill: promote existing free-text class_group values to rows ──────
    conn = op.get_bind()
    backfill_sql = sa.text(
        """
        INSERT INTO school_class (school_id, name, level, created_at)
        SELECT a.school_id, a.class_group AS name,
               MIN(a.level) AS level, CURRENT_TIMESTAMP AS created_at
        FROM accounts a
        WHERE a.class_group IS NOT NULL
          AND TRIM(a.class_group) != ''
          AND a.school_id IS NOT NULL
        GROUP BY a.school_id, a.class_group
        """
    )
    conn.execute(backfill_sql)

    update_sql = sa.text(
        """
        UPDATE accounts
        SET class_id = (
            SELECT sc.id FROM school_class sc
            WHERE sc.school_id = accounts.school_id
              AND sc.name = accounts.class_group
            LIMIT 1
        )
        WHERE accounts.class_group IS NOT NULL
        """
    )
    conn.execute(update_sql)

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_accounts_class_id', 'school_class', ['class_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_accounts_class_id', type_='foreignkey')
    if _column_exists('accounts', 'class_id'):
        with op.batch_alter_table('accounts', schema=None) as batch_op:
            batch_op.drop_column('class_id')
    if _table_exists('school_class'):
        op.drop_table('school_class')
