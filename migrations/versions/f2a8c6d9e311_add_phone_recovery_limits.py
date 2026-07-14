"""Add phone password recovery limits.

Revision ID: f2a8c6d9e311
Revises: e7c2d4a9f110
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2a8c6d9e311'
down_revision = 'e7c2d4a9f110'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('phone_recovery_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.String(length=20), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(), nullable=True),
        sa.Column('window_started_at', sa.DateTime(), nullable=True),
        sa.Column('send_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_verifications', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('student_id'))
    op.create_index('ix_phone_recovery_attempt_student_id', 'phone_recovery_attempt', ['student_id'])

def downgrade():
    op.drop_index('ix_phone_recovery_attempt_student_id', table_name='phone_recovery_attempt')
    op.drop_table('phone_recovery_attempt')
