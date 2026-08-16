"""Add recovery email to administrator-assisted recovery requests.

Revision ID: 1b8d7c9e4f20
Revises: c7d3e9f1a204
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa


revision = '1b8d7c9e4f20'
down_revision = 'c7d3e9f1a204'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('recovery_request')}
    if 'recovery_email' not in columns:
        op.add_column('recovery_request', sa.Column('recovery_email', sa.String(length=120), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('recovery_request')}
    if 'recovery_email' in columns:
        op.drop_column('recovery_request', 'recovery_email')
