"""Add private message inbox indexes

Revision ID: 6b8d4f9a2c31
Revises: 2613617165af
Create Date: 2026-08-18 09:58:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '6b8d4f9a2c31'
down_revision = '2613617165af'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_private_message_sender_timestamp',
        'private_message',
        ['sender_id', 'timestamp']
    )
    op.create_index(
        'ix_private_message_receiver_timestamp',
        'private_message',
        ['receiver_id', 'timestamp']
    )


def downgrade():
    op.drop_index(
        'ix_private_message_receiver_timestamp',
        table_name='private_message'
    )
    op.drop_index(
        'ix_private_message_sender_timestamp',
        table_name='private_message'
    )
