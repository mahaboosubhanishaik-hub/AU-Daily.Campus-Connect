"""Add administrator-assisted password recovery requests.

Revision ID: c7d3e9f1a204
Revises: f2a8c6d9e311
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d3e9f1a204'
down_revision = 'f2a8c6d9e311'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'recovery_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.String(length=20), nullable=False),
        sa.Column('contact_note', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='Pending'),
        sa.Column('reviewed_by', sa.String(length=20), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_recovery_request_student_id', 'recovery_request', ['student_id'])
    op.create_index('ix_recovery_request_status', 'recovery_request', ['status'])
    op.create_index('ix_recovery_request_created_at', 'recovery_request', ['created_at'])


def downgrade():
    op.drop_index('ix_recovery_request_created_at', table_name='recovery_request')
    op.drop_index('ix_recovery_request_status', table_name='recovery_request')
    op.drop_index('ix_recovery_request_student_id', table_name='recovery_request')
    op.drop_table('recovery_request')
