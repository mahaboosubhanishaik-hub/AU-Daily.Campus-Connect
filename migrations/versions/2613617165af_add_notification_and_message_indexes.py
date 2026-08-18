"""Add notification and message indexes

Revision ID: 2613617165af
Revises: 7c34251ee439
Create Date: 2026-08-17 16:20:22.481242

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2613617165af'
down_revision = '7c34251ee439'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_notification_user_unread',
        'notification',
        ['user_id', 'is_read']
    )
    op.create_index(
        'ix_private_message_receiver_unread',
        'private_message',
        ['receiver_id', 'is_read']
    )


def downgrade():
    op.drop_index(
        'ix_private_message_receiver_unread',
        table_name='private_message'
    )
    op.drop_index(
        'ix_notification_user_unread',
        table_name='notification'
    )
