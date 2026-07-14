"""Add admin response fields to reports and feedback.

Revision ID: e7c2d4a9f110
Revises: b6f8a2c1d9e0
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7c2d4a9f110'
down_revision = 'b6f8a2c1d9e0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('feedback') as batch_op:
        batch_op.add_column(sa.Column('admin_response', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('responded_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('report') as batch_op:
        batch_op.add_column(sa.Column('admin_response', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('responded_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('report') as batch_op:
        batch_op.drop_column('responded_at')
        batch_op.drop_column('admin_response')
    with op.batch_alter_table('feedback') as batch_op:
        batch_op.drop_column('responded_at')
        batch_op.drop_column('admin_response')
