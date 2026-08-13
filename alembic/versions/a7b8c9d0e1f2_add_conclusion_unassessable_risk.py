"""add conclusion and unassessable_risk to analysis_snapshots

Revision ID: a7b8c9d0e1f2
Revises: f1a3b5c7d9e1
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f1a3b5c7d9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 不支持 ALTER COLUMN 改列类型，必须用 batch 模式整表重建
    with op.batch_alter_table('analysis_snapshots') as batch_op:
        batch_op.add_column(sa.Column('conclusion', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('unassessable_risk', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.alter_column('signal', type_=sa.String(20), existing_type=sa.String(10))


def downgrade() -> None:
    with op.batch_alter_table('analysis_snapshots') as batch_op:
        batch_op.alter_column('signal', type_=sa.String(10), existing_type=sa.String(20))
        batch_op.drop_column('unassessable_risk')
        batch_op.drop_column('conclusion')
