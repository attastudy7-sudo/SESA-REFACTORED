"""add counsellor role, phone, audit_log

Revision ID: 4838ee558eeb
Revises: 3e9d32f2cbbe
Create Date: 2026-03-12 23:50:37.148131

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = '4838ee558eeb'
down_revision = '3e9d32f2cbbe'
branch_labels = None
depends_on = None


def index_exists(name):
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :name"
    ), {"name": name})
    return result.fetchone() is not None


def column_exists(table, column):
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.fetchone() is not None


def constraint_exists(name):
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = :name"
    ), {"name": name})
    return result.fetchone() is not None


def upgrade():
    # accounts — add is_counsellor only if missing
    if not column_exists('accounts', 'is_counsellor'):
        op.add_column('accounts', sa.Column('is_counsellor', sa.Boolean(), server_default='false', nullable=False))

    op.alter_column('accounts', 'email', existing_type=sa.VARCHAR(length=100), type_=sa.String(length=120), existing_nullable=False)
    op.alter_column('accounts', 'password', existing_type=sa.VARCHAR(length=200), type_=sa.String(length=256), existing_nullable=False)

    if not index_exists('ix_accounts_email'):
        op.create_index('ix_accounts_email', 'accounts', ['email'], unique=True)
    if not index_exists('ix_accounts_school_id'):
        op.create_index('ix_accounts_school_id', 'accounts', ['school_id'], unique=False)
    if not index_exists('ix_accounts_username'):
        op.create_index('ix_accounts_username', 'accounts', ['username'], unique=True)

    # question
    if not index_exists('ix_question_test_type'):
        op.create_index('ix_question_test_type', 'question', ['test_type'], unique=False)

    # school
    op.alter_column('school', 'email', existing_type=sa.VARCHAR(length=50), type_=sa.String(length=120), existing_nullable=True)
    if not index_exists('ix_school_access_code'):
        op.create_index('ix_school_access_code', 'school', ['access_code'], unique=True)
    if not index_exists('ix_school_qr_token'):
        op.create_index('ix_school_qr_token', 'school', ['qr_token'], unique=True)
    if not constraint_exists('uq_school_school_name'):
        op.create_unique_constraint('uq_school_school_name', 'school', ['school_name'])

    # test_results
    if not index_exists('ix_test_results_stage'):
        op.create_index('ix_test_results_stage', 'test_results', ['stage'], unique=False)
    if not index_exists('ix_test_results_taken_at'):
        op.create_index('ix_test_results_taken_at', 'test_results', ['taken_at'], unique=False)
    if not index_exists('ix_test_results_test_type'):
        op.create_index('ix_test_results_test_type', 'test_results', ['test_type'], unique=False)
    if not index_exists('ix_test_results_user_id'):
        op.create_index('ix_test_results_user_id', 'test_results', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_test_results_user_id', table_name='test_results')
    op.drop_index('ix_test_results_test_type', table_name='test_results')
    op.drop_index('ix_test_results_taken_at', table_name='test_results')
    op.drop_index('ix_test_results_stage', table_name='test_results')
    op.drop_constraint('uq_school_school_name', 'school', type_='unique')
    op.drop_index('ix_school_qr_token', table_name='school')
    op.drop_index('ix_school_access_code', table_name='school')
    op.alter_column('school', 'email', existing_type=sa.String(length=120), type_=sa.VARCHAR(length=50), existing_nullable=True)
    op.drop_index('ix_question_test_type', table_name='question')
    op.drop_index('ix_accounts_username', table_name='accounts')
    op.drop_index('ix_accounts_school_id', table_name='accounts')
    op.drop_index('ix_accounts_email', table_name='accounts')
    op.alter_column('accounts', 'password', existing_type=sa.String(length=256), type_=sa.VARCHAR(length=200), existing_nullable=False)
    op.alter_column('accounts', 'email', existing_type=sa.String(length=120), type_=sa.VARCHAR(length=100), existing_nullable=False)
    op.drop_column('accounts', 'is_counsellor')