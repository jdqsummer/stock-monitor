"""add stage_results and financials_8p to analysis_snapshots

Revision ID: 6b4d8e2f1a9c
Revises: a7b8c9d0e1f2
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6b4d8e2f1a9c'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('analysis_snapshots') as batch_op:
        batch_op.add_column(sa.Column('stage_results', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('financials_8p', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('analysis_snapshots') as batch_op:
        batch_op.drop_column('financials_8p')
        batch_op.drop_column('stage_results')
