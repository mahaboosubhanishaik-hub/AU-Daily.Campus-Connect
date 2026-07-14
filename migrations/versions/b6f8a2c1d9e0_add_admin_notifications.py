"""Add administrator notifications.

Revision ID: b6f8a2c1d9e0
Revises: f03915c0a136
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa


revision = 'b6f8a2c1d9e0'
down_revision = 'f03915c0a136'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_notification',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('message', sa.String(length=255), nullable=False),
        sa.Column('link', sa.String(length=255), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_admin_notification_is_read', 'admin_notification', ['is_read'])
    op.create_index('ix_admin_notification_timestamp', 'admin_notification', ['timestamp'])


def downgrade():
    op.drop_index('ix_admin_notification_timestamp', table_name='admin_notification')
    op.drop_index('ix_admin_notification_is_read', table_name='admin_notification')
    op.drop_table('admin_notification')
