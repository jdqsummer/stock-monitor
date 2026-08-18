"""unique reminder dedup index

Revision ID: c1d2e3f4a5b6
Revises: b7d9e1f2a3c4
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b7d9e1f2a3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 去掉旧的 (user_id, category, reminder_date) 非唯一索引，
    # 换成 (user_id, category, code, reminder_date) 唯一索引 —— DB 层强制去重。
    op.drop_index('ix_reminders_user_cat_date', table_name='reminders')
    op.create_index('ix_reminders_user_cat_code_date', 'reminders',
                    ['user_id', 'category', 'code', 'reminder_date'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_reminders_user_cat_code_date', table_name='reminders')
    op.create_index('ix_reminders_user_cat_date', 'reminders',
                    ['user_id', 'category', 'reminder_date'])
