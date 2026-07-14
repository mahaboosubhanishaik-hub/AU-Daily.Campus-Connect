"""Add persistent authentication rate limits.

Revision ID: a3e4f5a6b7c8
Revises: c7d3e9f1a204
"""
from alembic import op
import sqlalchemy as sa


revision = "a3e4f5a6b7c8"
down_revision = "c7d3e9f1a204"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_rate_limit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_auth_rate_limit_key"), "auth_rate_limit", ["key"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_auth_rate_limit_key"), table_name="auth_rate_limit")
    op.drop_table("auth_rate_limit")
