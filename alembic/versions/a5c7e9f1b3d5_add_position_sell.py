"""add position nullable + industry + analysis_snapshots sell group

Revision ID: a5c7e9f1b3d5
Revises: a4b6c8d0e2f4
Create Date: 2026-08-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c7e9f1b3d5'
down_revision: Union[str, None] = 'a4b6c8d0e2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('positions') as bop:
        bop.alter_column('shares', existing_type=sa.Float(), nullable=True)
        bop.alter_column('cost_price', existing_type=sa.Float(), nullable=True)
        bop.add_column(sa.Column('industry', sa.String(100), nullable=True))
        bop.add_column(sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False))
        bop.create_unique_constraint('uq_position_user_code', ['user_id', 'stock_code'])
    with op.batch_alter_table('analysis_snapshots') as bop:
        bop.add_column(sa.Column('analysis_mode', sa.String(20), server_default='watchlist', nullable=False))
        bop.add_column(sa.Column('sell_pe_low', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_pe_high', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_pe_rationale', sa.Text(), nullable=True))
        bop.add_column(sa.Column('sell_market_cap_low', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_market_cap_high', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_price_low', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_price_high', sa.Float(), server_default='0', nullable=False))
        bop.add_column(sa.Column('sell_distance_pct', sa.Float(), nullable=True))
        bop.add_column(sa.Column('sell_signal', sa.String(20), server_default='none', nullable=False))
        bop.add_column(sa.Column('sell_action', sa.String(20), nullable=True))
        bop.add_column(sa.Column('sell_analysis', sa.Text(), nullable=True))
        bop.add_column(sa.Column('stage_results_sell', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('positions') as bop:
        bop.drop_constraint('uq_position_user_code', type_='unique')
        bop.drop_column('updated_at')
        bop.drop_column('industry')
        bop.alter_column('cost_price', existing_type=sa.Float(), nullable=False)
        bop.alter_column('shares', existing_type=sa.Float(), nullable=False)
    with op.batch_alter_table('analysis_snapshots') as bop:
        for col in ('stage_results_sell', 'sell_analysis', 'sell_action', 'sell_signal',
                    'sell_distance_pct', 'sell_price_high', 'sell_price_low',
                    'sell_market_cap_high', 'sell_market_cap_low', 'sell_pe_rationale',
                    'sell_pe_high', 'sell_pe_low', 'analysis_mode'):
            bop.drop_column(col)
