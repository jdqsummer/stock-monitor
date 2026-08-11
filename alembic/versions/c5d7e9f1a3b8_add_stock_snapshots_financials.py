"""add stock_snapshots and financials tables

Revision ID: c5d7e9f1a3b8
Revises: b3e5f7a8c9d1
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d7e9f1a3b8'
down_revision: Union[str, None] = 'b3e5f7a8c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A 表：行情快照（跨用户共享，按 code 一行）
    op.create_table(
        'stock_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('current_price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('change_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('total_market_cap', sa.Float(), nullable=False, server_default='0'),
        sa.Column('pe_dynamic', sa.Float(), nullable=True),
        sa.Column('total_shares', sa.Float(), nullable=True),
        sa.Column('update_time', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_stock_snapshots_code'), 'stock_snapshots', ['code'], unique=True)

    # A 表：财报（按 (code, report_period) 一行）
    op.create_table(
        'financials',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('report_period', sa.String(20), nullable=False),
        sa.Column('revenue', sa.Float(), nullable=True),
        sa.Column('net_profit_parent', sa.Float(), nullable=True),
        sa.Column('net_profit_deducted', sa.Float(), nullable=True),
        sa.Column('roe', sa.Float(), nullable=True),
        sa.Column('is_official', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('code', 'report_period', name='uq_financials_code_period'),
    )
    op.create_index(op.f('ix_financials_code'), 'financials', ['code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_financials_code'), table_name='financials')
    op.drop_table('financials')
    op.drop_index(op.f('ix_stock_snapshots_code'), table_name='stock_snapshots')
    op.drop_table('stock_snapshots')
