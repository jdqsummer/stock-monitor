"""add qualitative columns to analysis_snapshots

Revision ID: d9f1a3b5c7e1
Revises: c5d7e9f1a3b8
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f1a3b5c7e1'
down_revision: Union[str, None] = 'c5d7e9f1a3b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_snapshots', sa.Column('industry_category', sa.String(100), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('moat_assessment', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('risk_factors', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('pe_rationale', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('recommendation', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('signal_label', sa.String(50), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('profit_quality_ok', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('analysis_snapshots', sa.Column('profit_quality_warnings', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('analysis_source', sa.String(20), nullable=False, server_default='manual'))
    op.add_column('analysis_snapshots', sa.Column('analysis_completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in ['analysis_completed_at', 'analysis_source', 'profit_quality_warnings',
                'profit_quality_ok', 'signal_label', 'recommendation', 'pe_rationale',
                'risk_factors', 'moat_assessment', 'industry_category']:
        op.drop_column('analysis_snapshots', col)
