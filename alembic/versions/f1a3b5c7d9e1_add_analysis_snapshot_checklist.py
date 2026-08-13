"""add checklist columns to analysis_snapshots

Revision ID: f1a3b5c7d9e1
Revises: d9f1a3b5c7e1
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a3b5c7d9e1'
down_revision: Union[str, None] = 'd9f1a3b5c7e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_snapshots', sa.Column('checklist_results', sa.Text(), nullable=True))
    op.add_column('analysis_snapshots', sa.Column('checklist_veto', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('analysis_snapshots', sa.Column('checklist_summary', sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ['checklist_summary', 'checklist_veto', 'checklist_results']:
        op.drop_column('analysis_snapshots', col)
