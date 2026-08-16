"""Add projects, notices, skills, and suggestions.

Revision ID: 2c4d5e6f7a81
Revises: 1b8d7c9e4f20, a3e4f5a6b7c8
Create Date: 2026-08-03
"""
from alembic import op
import sqlalchemy as sa


revision = '2c4d5e6f7a81'
down_revision = ('1b8d7c9e4f20', 'a3e4f5a6b7c8')
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def has_column(table_name, column_name):
        if table_name not in tables:
            return False
        return column_name in {column['name'] for column in inspector.get_columns(table_name)}

    def has_index(table_name, index_name):
        if table_name not in tables:
            return False
        return index_name in {index['name'] for index in inspector.get_indexes(table_name)}

    if not has_column('lost_item', 'category'):
        op.add_column('lost_item', sa.Column('category', sa.String(length=50), nullable=True))

    if 'student_skill' not in tables:
        op.create_table(
            'student_skill',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('student_id', sa.String(length=20), nullable=False),
            sa.Column('skill_name', sa.String(length=100), nullable=False),
            sa.ForeignKeyConstraint(['student_id'], ['student.student_id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('student_id', 'skill_name', name='_student_skill_uc'),
        )
        tables.add('student_skill')

    if 'notice' not in tables:
        op.create_table(
            'notice',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('department', sa.String(length=100), nullable=False),
            sa.Column('file_path', sa.String(length=200), nullable=True),
            sa.Column('posted_by_admin_id', sa.String(length=20), nullable=False),
            sa.Column('is_urgent', sa.Boolean(), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['posted_by_admin_id'], ['admin.admin_id']),
            sa.PrimaryKeyConstraint('id'),
        )
        tables.add('notice')
    if not has_index('notice', 'ix_notice_timestamp'):
        op.create_index('ix_notice_timestamp', 'notice', ['timestamp'])

    if 'project' not in tables:
        op.create_table(
            'project',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('technologies', sa.String(length=500), nullable=True),
            sa.Column('image_file', sa.String(length=200), nullable=True),
            sa.Column('video_file', sa.String(length=200), nullable=True),
            sa.Column('github_link', sa.String(length=500), nullable=True),
            sa.Column('live_demo_link', sa.String(length=500), nullable=True),
            sa.Column('user_id', sa.String(length=20), nullable=False),
            sa.Column('user_name', sa.String(length=100), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['student.student_id']),
            sa.PrimaryKeyConstraint('id'),
        )
        tables.add('project')
    if not has_index('project', 'ix_project_timestamp'):
        op.create_index('ix_project_timestamp', 'project', ['timestamp'])

    if 'suggestion' not in tables:
        op.create_table(
            'suggestion',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('category', sa.String(length=100), nullable=True),
            sa.Column('user_id', sa.String(length=20), nullable=True),
            sa.Column('admin_notes', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=50), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        tables.add('suggestion')

    if 'skill_endorsement' not in tables:
        op.create_table(
            'skill_endorsement',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('skill_id', sa.Integer(), nullable=False),
            sa.Column('endorser_student_id', sa.String(length=20), nullable=False),
            sa.ForeignKeyConstraint(['endorser_student_id'], ['student.student_id']),
            sa.ForeignKeyConstraint(['skill_id'], ['student_skill.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('skill_id', 'endorser_student_id', name='_skill_endorser_uc'),
        )
        tables.add('skill_endorsement')

    if 'project_like' not in tables:
        op.create_table(
            'project_like',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.String(length=20), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['project_id'], ['project.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'project_id', name='_user_project_like_uc'),
        )
        tables.add('project_like')

    if 'project_comment' not in tables:
        op.create_table(
            'project_comment',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('user_id', sa.String(length=20), nullable=False),
            sa.Column('user_name', sa.String(length=100), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['project_id'], ['project.id']),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_table('project_comment')
    op.drop_table('project_like')
    op.drop_table('skill_endorsement')
    op.drop_table('suggestion')
    op.drop_index('ix_project_timestamp', table_name='project')
    op.drop_table('project')
    op.drop_index('ix_notice_timestamp', table_name='notice')
    op.drop_table('notice')
    op.drop_table('student_skill')
    op.drop_column('lost_item', 'category')
