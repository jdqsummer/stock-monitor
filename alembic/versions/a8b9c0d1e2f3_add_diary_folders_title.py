"""add diary_folders table + diaries title/parent_folder_id

Revision ID: a8b9c0d1e2f3
Revises: d3e5f7a9b1c2
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'd3e5f7a9b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'diary_folders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('parent_id', sa.String(36), sa.ForeignKey('diary_folders.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_diary_folders_user_id', 'diary_folders', ['user_id'])
    # SQLite 不支持对已存在表 ALTER 增加约束（含 FK），须用 batch 模式重建表；
    # batch 模式要求 FK 必须显式命名
    with op.batch_alter_table('diaries') as batch_op:
        batch_op.add_column(sa.Column('title', sa.String(255), nullable=True))
        batch_op.add_column(sa.Column(
            'parent_folder_id',
            sa.String(36),
            sa.ForeignKey('diary_folders.id', name='fk_diaries_parent_folder_id'),
            nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table('diaries') as batch_op:
        batch_op.drop_column('parent_folder_id')
        batch_op.drop_column('title')
    op.drop_index('ix_diary_folders_user_id', table_name='diary_folders')
    op.drop_table('diary_folders')
