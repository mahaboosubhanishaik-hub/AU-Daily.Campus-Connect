"""Add active page performance indexes

Revision ID: d4f7a8b9c012
Revises: 6b8d4f9a2c31
Create Date: 2026-08-18 10:15:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'd4f7a8b9c012'
down_revision = '6b8d4f9a2c31'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_event_date', 'event', ['date'])
    op.create_index('ix_event_user_id', 'event', ['user_id'])
    op.create_index('ix_event_registration_user_event', 'event_registration', ['user_id', 'event_id'])
    op.create_index('ix_event_like_user_event', 'event_like', ['user_id', 'event_id'])
    op.create_index('ix_news_like_user_post', 'news_like', ['user_id', 'post_id'])
    op.create_index('ix_news_comment_post_timestamp', 'news_comment', ['post_id', 'timestamp'])
    op.create_index('ix_poll_vote_poll_user', 'poll_vote', ['poll_id', 'user_id'])
    op.create_index('ix_poll_vote_option', 'poll_vote', ['option_id'])
    op.create_index('ix_doubt_reply_doubt', 'doubt_reply', ['doubt_id'])
    op.create_index('ix_task_user_completed_timestamp', 'task', ['user_id', 'is_completed', 'timestamp'])
    op.create_index('ix_notice_department_urgent_timestamp', 'notice', ['department', 'is_urgent', 'timestamp'])
    op.create_index('ix_saved_resource_user_resource', 'saved_resource', ['user_id', 'resource_id'])


def downgrade():
    op.drop_index('ix_saved_resource_user_resource', table_name='saved_resource')
    op.drop_index('ix_notice_department_urgent_timestamp', table_name='notice')
    op.drop_index('ix_task_user_completed_timestamp', table_name='task')
    op.drop_index('ix_doubt_reply_doubt', table_name='doubt_reply')
    op.drop_index('ix_poll_vote_option', table_name='poll_vote')
    op.drop_index('ix_poll_vote_poll_user', table_name='poll_vote')
    op.drop_index('ix_news_comment_post_timestamp', table_name='news_comment')
    op.drop_index('ix_news_like_user_post', table_name='news_like')
    op.drop_index('ix_event_like_user_event', table_name='event_like')
    op.drop_index('ix_event_registration_user_event', table_name='event_registration')
    op.drop_index('ix_event_user_id', table_name='event')
    op.drop_index('ix_event_date', table_name='event')
