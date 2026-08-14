"""add analysis_model analysis_degraded to analysis_snapshots

Revision ID: 2b82e6c3f525
Revises: 6b4d8e2f1a9c
Create Date: 2026-08-14 23:30:04.221724
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b82e6c3f525'
down_revision: Union[str, None] = '6b4d8e2f1a9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 元数据契约三字段：实际路由模型 + 降级标记
    # analysis_degraded 为 NOT NULL 布尔，SQLite 加非空列必须有默认值（server_default='0'）
    op.add_column('analysis_snapshots', sa.Column('analysis_model', sa.String(length=50), nullable=True))
    op.add_column('analysis_snapshots', sa.Column(
        'analysis_degraded', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('analysis_snapshots', 'analysis_degraded')
    op.drop_column('analysis_snapshots', 'analysis_model')
