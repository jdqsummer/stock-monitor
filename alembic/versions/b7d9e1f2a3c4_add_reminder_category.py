"""add reminders category + title

Revision ID: b7d9e1f2a3c4
Revises: a5c7e9f1b3d5
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d9e1f2a3c4'
down_revision: Union[str, None] = 'a5c7e9f1b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reminders') as bop:
        bop.add_column(sa.Column('category', sa.String(20), server_default='strike', nullable=False))
        bop.add_column(sa.Column('title', sa.String(200), nullable=True))
    op.create_index('ix_reminders_user_cat_date', 'reminders',
                    ['user_id', 'category', 'reminder_date'])


def downgrade() -> None:
    op.drop_index('ix_reminders_user_cat_date', table_name='reminders')
    with op.batch_alter_table('reminders') as bop:
        bop.drop_column('title')
        bop.drop_column('category')
