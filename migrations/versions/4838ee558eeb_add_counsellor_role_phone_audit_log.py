"""add counsellor role, phone, audit_log

Revision ID: 4838ee558eeb
Revises: 3e9d32f2cbbe
Create Date: 2026-03-12 23:50:37.148131

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '4838ee558eeb'
down_revision = '3e9d32f2cbbe'
branch_labels = None
depends_on = None


def index_exists(name):
    inspector = inspect(op.get_bind())
    for table in inspector.get_table_names():
        for idx in inspector.get_indexes(table):
            if idx['name'] == name:
                return True
    return False


def column_exists(table, column):
    inspector = inspect(op.get_bind())
    return column in [c['name'] for c in inspector.get_columns(table)]


def upgrade():
    # accounts — add missing columns
    if not column_exists('accounts', 'is_counsellor'):
        op.add_column('accounts', sa.Column('is_counsellor', sa.Boolean(), server_default='0', nullable=False))
    if not column_exists('accounts', 'phone'):
        op.add_column('accounts', sa.Column('phone', sa.String(length=20), nullable=True))

    if not index_exists('ix_accounts_email'):
        op.create_index('ix_accounts_email', 'accounts', ['email'], unique=True)
    if not index_exists('ix_accounts_school_id'):
        op.create_index('ix_accounts_school_id', 'accounts', ['school_id'], unique=False)
    if not index_exists('ix_accounts_username'):
        op.create_index('ix_accounts_username', 'accounts', ['username'], unique=True)

    # question
    if not index_exists('ix_question_test_type'):
        op.create_index('ix_question_test_type', 'question', ['test_type'], unique=False)

    # school — add missing columns
    if not column_exists('school', 'phone'):
        op.add_column('school', sa.Column('phone', sa.String(length=20), nullable=True))
    if not column_exists('school', 'access_code'):
        op.add_column('school', sa.Column('access_code', sa.String(length=8), nullable=True))
    if not column_exists('school', 'qr_token'):
        op.add_column('school', sa.Column('qr_token', sa.String(length=64), nullable=True))

    if not index_exists('ix_school_access_code'):
        op.create_index('ix_school_access_code', 'school', ['access_code'], unique=True)
    if not index_exists('ix_school_qr_token'):
        op.create_index('ix_school_qr_token', 'school', ['qr_token'], unique=True)

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
    op.drop_index('ix_school_qr_token', table_name='school')
    op.drop_index('ix_school_access_code', table_name='school')
    with op.batch_alter_table('school') as batch_op:
        batch_op.drop_column('qr_token')
        batch_op.drop_column('access_code')
        batch_op.drop_column('phone')
    op.drop_index('ix_question_test_type', table_name='question')
    op.drop_index('ix_accounts_username', table_name='accounts')
    op.drop_index('ix_accounts_school_id', table_name='accounts')
    op.drop_index('ix_accounts_email', table_name='accounts')
    with op.batch_alter_table('accounts') as batch_op:
        batch_op.drop_column('phone')
        batch_op.drop_column('is_counsellor')