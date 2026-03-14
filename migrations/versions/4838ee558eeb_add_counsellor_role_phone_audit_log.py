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

    # school — add missing columns before indexing them
    op.alter_column('school', 'email', existing_type=sa.VARCHAR(length=50), type_=sa.String(length=120), existing_nullable=True)

    if not column_exists('school', 'upload_enabled'):
        op.add_column('school', sa.Column('upload_enabled', sa.Boolean(), server_default='false', nullable=False))
    if not column_exists('school', 'paystack_reference'):
        op.add_column('school', sa.Column('paystack_reference', sa.String(length=100), nullable=True))
    if not column_exists('school', 'payment_date'):
        op.add_column('school', sa.Column('payment_date', sa.DateTime(), nullable=True))
    if not column_exists('school', 'subscription_expires'):
        op.add_column('school', sa.Column('subscription_expires', sa.DateTime(), nullable=True))
    if not column_exists('school', 'access_code'):
        op.add_column('school', sa.Column('access_code', sa.String(length=8), nullable=True))
    if not column_exists('school', 'qr_token'):
        op.add_column('school', sa.Column('qr_token', sa.String(length=64), nullable=True))
    if not column_exists('school', 'failed_attempts'):
        op.add_column('school', sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False))
    if not column_exists('school', 'locked_until'):
        op.add_column('school', sa.Column('locked_until', sa.DateTime(), nullable=True))

    if not index_exists('ix_school_access_code'):
        op.create_index('ix_school_access_code', 'school', ['access_code'], unique=True)
    if not index_exists('ix_school_qr_token'):
        op.create_index('ix_school_qr_token', 'school', ['qr_token'], unique=True)
    if not index_exists('ix_school_subscription_expires'):
        op.create_index('ix_school_subscription_expires', 'school', ['subscription_expires'], unique=False)
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
    if index_exists('ix_school_subscription_expires'):
        op.drop_index('ix_school_subscription_expires', table_name='school')
    op.drop_index('ix_school_qr_token', table_name='school')
    op.drop_index('ix_school_access_code', table_name='school')
    op.drop_column('school', 'locked_until')
    op.drop_column('school', 'failed_attempts')
    op.drop_column('school', 'qr_token')
    op.drop_column('school', 'access_code')
    op.drop_column('school', 'subscription_expires')
    op.drop_column('school', 'payment_date')
    op.drop_column('school', 'paystack_reference')
    op.drop_column('school', 'upload_enabled')
    op.alter_column('school', 'email', existing_type=sa.String(length=120), type_=sa.VARCHAR(length=50), existing_nullable=True)
    op.drop_index('ix_question_test_type', table_name='question')
    op.drop_index('ix_accounts_username', table_name='accounts')
    op.drop_index('ix_accounts_school_id', table_name='accounts')
    op.drop_index('ix_accounts_email', table_name='accounts')
    op.alter_column('accounts', 'password', existing_type=sa.String(length=256), type_=sa.VARCHAR(length=200), existing_nullable=False)
    op.alter_column('accounts', 'email', existing_type=sa.String(length=120), type_=sa.VARCHAR(length=100), existing_nullable=False)
    op.drop_column('accounts', 'is_counsellor')