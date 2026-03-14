"""Fresh schema — complete baseline matching all current models.

Replaces the previous 4-migration chain:
  3e9d32f2cbbe  initial_migration
  4838ee558eeb  add_counsellor_role_phone_audit_log
  b9900ac3e06c  subscription_expiry_date
  c1a3f7e92d04  account_lockout

Revision ID: 0001_fresh_schema
Revises:
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_fresh_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ── question ──────────────────────────────────────────────
    op.create_table(
        'question',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('test_type', sa.String(length=100), nullable=False),
        sa.Column('question_content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_question_test_type', 'question', ['test_type'], unique=False)

    # ── school ────────────────────────────────────────────────
    op.create_table(
        'school',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_name', sa.String(length=200), nullable=False),
        sa.Column('admin_name', sa.String(length=100), nullable=False),
        sa.Column('admin_password', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('subscription_paid', sa.Boolean(), nullable=True),
        sa.Column('upload_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('paystack_reference', sa.String(length=100), nullable=True),
        sa.Column('payment_date', sa.DateTime(), nullable=True),
        sa.Column('subscription_expires', sa.DateTime(), nullable=True),
        sa.Column('access_code', sa.String(length=8), nullable=True),
        sa.Column('qr_token', sa.String(length=64), nullable=True),
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('school_name'),
    )
    op.create_index('ix_school_access_code', 'school', ['access_code'], unique=True)
    op.create_index('ix_school_qr_token', 'school', ['qr_token'], unique=True)
    op.create_index('ix_school_subscription_expires', 'school', ['subscription_expires'], unique=False)

    # ── accounts ──────────────────────────────────────────────
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fname', sa.String(length=100), nullable=False),
        sa.Column('lname', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password', sa.String(length=256), nullable=False),
        sa.Column('level', sa.String(length=50), nullable=True),
        sa.Column('gender', sa.String(length=20), nullable=True),
        sa.Column('birthdate', sa.Date(), nullable=True),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('class_group', sa.String(length=50), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_counsellor', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['school_id'], ['school.id'],
                                name='fk_accounts_school_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_accounts_email', 'accounts', ['email'], unique=True)
    op.create_index('ix_accounts_username', 'accounts', ['username'], unique=True)
    op.create_index('ix_accounts_school_id', 'accounts', ['school_id'], unique=False)

    # ── test_results ──────────────────────────────────────────
    op.create_table(
        'test_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('test_type', sa.String(length=100), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('max_score', sa.Integer(), nullable=True),
        sa.Column('stage', sa.String(length=50), nullable=True),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('taken_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_test_results_user_id', 'test_results', ['user_id'], unique=False)
    op.create_index('ix_test_results_test_type', 'test_results', ['test_type'], unique=False)
    op.create_index('ix_test_results_stage', 'test_results', ['stage'], unique=False)
    op.create_index('ix_test_results_taken_at', 'test_results', ['taken_at'], unique=False)

    # ── audit_log ─────────────────────────────────────────────
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['school_id'], ['school.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_event_type', 'audit_log', ['event_type'], unique=False)
    op.create_index('ix_audit_log_actor_id', 'audit_log', ['actor_id'], unique=False)
    op.create_index('ix_audit_log_school_id', 'audit_log', ['school_id'], unique=False)
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'], unique=False)


def downgrade():
    op.drop_table('audit_log')
    op.drop_table('test_results')
    op.drop_table('accounts')
    op.drop_table('school')
    op.drop_table('question')