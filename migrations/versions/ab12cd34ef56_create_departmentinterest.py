"""Create department_interest table

Revision ID: ab12cd34ef56
Revises: 98b7c6d5a4f3
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'ab12cd34ef56'
down_revision = '98b7c6d5a4f3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'department_interest',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('department', sa.String(length=100), nullable=False),
        sa.Column('keywords', sa.Text(), nullable=False),
    )
    op.create_index('ix_department_interest_department', 'department_interest', ['department'], unique=True)


def downgrade():
    op.drop_index('ix_department_interest_department', table_name='department_interest')
    op.drop_table('department_interest')
