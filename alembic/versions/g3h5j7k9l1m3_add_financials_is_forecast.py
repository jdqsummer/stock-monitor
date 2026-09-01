"""add financials.is_forecast column

Revision ID: g3h5j7k9l1m3
Revises: f1a3b5c7d9e1
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g3h5j7k9l1m3'
# 修复（2026-09-01）：原误设 down_revision='f1a3b5c7d9e1'，但该 revision 已有
# 后继 a7b8c9d0e1f2，会形成分支导致 alembic upgrade head 失败。改为真正的 head。
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 修复 3（2026-09-01）：新增 is_forecast 字段与 is_official 互斥；
    # 历史数据默认 False（不视为预告，由 is_official=True 表达正式财报）
    with op.batch_alter_table("financials") as batch_op:
        batch_op.add_column(
            sa.Column("is_forecast", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    with op.batch_alter_table("financials") as batch_op:
        batch_op.drop_column("is_forecast")
