"""add counsellor role, phone, audit_log

Revision ID: 4838ee558eeb
Revises: 3e9d32f2cbbe
Create Date: 2026-03-12 23:50:37.148131

"""
from alembic import op
import sqlalchemy as sa


revision = '4838ee558eeb'
down_revision = '3e9d32f2cbbe'
branch_labels = None
depends_on = None


def upgrade():
    # audit_log table and its indexes already exist in DB — skip creation

    # Drop the leftover temp table from the failed previous run
    op.drop_table('_alembic_tmp_accounts')

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_counsellor', sa.Boolean(), server_default='0', nullable=False))
        batch_op.alter_column('email',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.String(length=120),
               existing_nullable=False)
        batch_op.alter_column('password',
               existing_type=sa.VARCHAR(length=200),
               type_=sa.String(length=256),
               existing_nullable=False)
        batch_op.create_index(batch_op.f('ix_accounts_email'), ['email'], unique=True)
        batch_op.create_index(batch_op.f('ix_accounts_school_id'), ['school_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_accounts_username'), ['username'], unique=True)

    with op.batch_alter_table('question', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_question_test_type'), ['test_type'], unique=False)

    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.alter_column('email',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=120),
               existing_nullable=True)
        batch_op.create_index(batch_op.f('ix_school_access_code'), ['access_code'], unique=True)
        batch_op.create_index(batch_op.f('ix_school_qr_token'), ['qr_token'], unique=True)
        batch_op.create_unique_constraint('uq_school_school_name', ['school_name'])

    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_test_results_stage'), ['stage'], unique=False)
        batch_op.create_index(batch_op.f('ix_test_results_taken_at'), ['taken_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_test_results_test_type'), ['test_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_test_results_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('test_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_results_user_id'))
        batch_op.drop_index(batch_op.f('ix_test_results_test_type'))
        batch_op.drop_index(batch_op.f('ix_test_results_taken_at'))
        batch_op.drop_index(batch_op.f('ix_test_results_stage'))

    with op.batch_alter_table('school', schema=None) as batch_op:
        batch_op.drop_constraint('uq_school_school_name', type_='unique')
        batch_op.drop_index(batch_op.f('ix_school_qr_token'))
        batch_op.drop_index(batch_op.f('ix_school_access_code'))
        batch_op.alter_column('email',
               existing_type=sa.String(length=120),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)

    with op.batch_alter_table('question', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_question_test_type'))

    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_accounts_username'))
        batch_op.drop_index(batch_op.f('ix_accounts_school_id'))
        batch_op.drop_index(batch_op.f('ix_accounts_email'))
        batch_op.alter_column('password',
               existing_type=sa.String(length=256),
               type_=sa.VARCHAR(length=200),
               existing_nullable=False)
        batch_op.alter_column('email',
               existing_type=sa.String(length=120),
               type_=sa.VARCHAR(length=100),
               existing_nullable=False)
        batch_op.drop_column('is_counsellor')

    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_school_id'))
        batch_op.drop_index(batch_op.f('ix_audit_log_event_type'))
        batch_op.drop_index(batch_op.f('ix_audit_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_log_actor_id'))

    op.drop_table('audit_log')