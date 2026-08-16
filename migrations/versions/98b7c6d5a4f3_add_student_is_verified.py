"""Add student email verification flag.

Revision ID: 98b7c6d5a4f3
Revises: f2a8c6d9e311
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa

revision = '98b7c6d5a4f3'
down_revision = '8e65b9398649'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'student',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )
    op.alter_column('student', 'is_verified', server_default=None)


def downgrade():
    op.drop_column('student', 'is_verified')
