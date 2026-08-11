"""redesign analysis_snapshots to numeric columns

Revision ID: b3e5f7a8c9d1
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e5f7a8c9d1'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 表为空壳（从未写入），直接重建为数值化结构
    op.drop_table('analysis_snapshots')
    op.create_table(
        'analysis_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('stock_code', sa.String(20), nullable=False),
        sa.Column('annual_profit_low', sa.Float(), nullable=False, server_default='0'),
        sa.Column('annual_profit_high', sa.Float(), nullable=False, server_default='0'),
        sa.Column('profit_method', sa.String(20), nullable=False, server_default=''),
        sa.Column('pe_low', sa.Float(), nullable=False, server_default='0'),
        sa.Column('pe_high', sa.Float(), nullable=False, server_default='0'),
        sa.Column('swing_market_cap_low', sa.Float(), nullable=False, server_default='0'),
        sa.Column('swing_market_cap_high', sa.Float(), nullable=False, server_default='0'),
        sa.Column('swing_price_low', sa.Float(), nullable=False, server_default='0'),
        sa.Column('swing_price_high', sa.Float(), nullable=False, server_default='0'),
        sa.Column('current_market_cap', sa.Float(), nullable=False, server_default='0'),
        sa.Column('current_price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('distance_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('signal', sa.String(10), nullable=False, server_default='none'),
        sa.Column('rating', sa.String(10), nullable=False, server_default=''),
        sa.Column('data_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'stock_code', name='uq_snapshot_user_code'),
    )


def downgrade() -> None:
    op.drop_table('analysis_snapshots')
    op.create_table(
        'analysis_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('stock_code', sa.String(20), nullable=False),
        sa.Column('annual_profit', sa.String(50), nullable=True),
        sa.Column('profit_method', sa.String(20), nullable=True),
        sa.Column('swing_pe', sa.String(50), nullable=True),
        sa.Column('swing_market_cap', sa.String(50), nullable=True),
        sa.Column('swing_price', sa.String(50), nullable=True),
        sa.Column('current_market_cap', sa.Float(), nullable=True),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('distance_pct', sa.Float(), nullable=True),
        sa.Column('rating', sa.String(10), nullable=True),
        sa.Column('data_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
