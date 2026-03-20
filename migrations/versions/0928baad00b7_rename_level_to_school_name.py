"""rename level to school_name

Revision ID: 0928baad00b7
Revises: a85b73caaa24
Create Date: 2026-03-20 02:09:34.150171

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0928baad00b7'
down_revision = 'a85b73caaa24'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('school_name', sa.String(length=200), nullable=True))
        batch_op.drop_column('level')


def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('level', sa.String(length=50), nullable=True))
        batch_op.drop_column('school_name')

        
    op.create_table('_alembic_tmp_accounts',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('fname', sa.VARCHAR(length=100), nullable=False),
    sa.Column('lname', sa.VARCHAR(length=100), nullable=False),
    sa.Column('email', sa.VARCHAR(length=120), nullable=False),
    sa.Column('username', sa.VARCHAR(length=50), nullable=False),
    sa.Column('password', sa.VARCHAR(length=256), nullable=False),
    sa.Column('level', sa.VARCHAR(length=50), nullable=True),
    sa.Column('gender', sa.VARCHAR(length=20), nullable=True),
    sa.Column('birthdate', sa.DATE(), nullable=True),
    sa.Column('last_login', sa.DATETIME(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('school_id', sa.INTEGER(), nullable=True),
    sa.Column('is_admin', sa.BOOLEAN(), server_default=sa.text('0'), nullable=False),
    sa.Column('class_group', sa.VARCHAR(length=50), nullable=True),
    sa.Column('is_counsellor', sa.BOOLEAN(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('failed_attempts', sa.INTEGER(), server_default=sa.text("'0'"), nullable=False),
    sa.Column('locked_until', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['school_id'], ['school.id'], name=op.f('fk_accounts_school_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('username')
    )
    # ### end Alembic commands ###
