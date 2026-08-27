"""add user.last_login_at + system_logs table

Revision ID: a9b0c1d2e3f4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-27 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users.last_login_at：登录成功后由 auth_svc 写入；可空（旧用户/新注册未登录）
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))

    # system_logs：管理后台持久化展示前端 console + 后端 logger.* 上报
    op.create_table(
        'system_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('path', sa.String(length=500), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_system_logs_created_at'), 'system_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_system_logs_user_id'), 'system_logs', ['user_id'], unique=False)
    # 查询热路径：按 level 过滤 + 按时间倒序；按 user 过滤 + 按时间倒序
    op.create_index('ix_system_logs_level_created', 'system_logs', ['level', 'created_at'], unique=False)
    op.create_index('ix_system_logs_user_created', 'system_logs', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_system_logs_user_created', table_name='system_logs')
    op.drop_index('ix_system_logs_level_created', table_name='system_logs')
    op.drop_index(op.f('ix_system_logs_user_id'), table_name='system_logs')
    op.drop_index(op.f('ix_system_logs_created_at'), table_name='system_logs')
    op.drop_table('system_logs')
    op.drop_column('users', 'last_login_at')
