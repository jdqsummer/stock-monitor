"""add unique constraint on watchlist (user_id, stock_code)

Revision ID: a1b2c3d4e5f6
Revises: e47556799a7f
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e47556799a7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('watchlist') as batch_op:
        batch_op.create_unique_constraint('uq_watchlist_user_stock', ['user_id', 'stock_code'])


def downgrade() -> None:
    with op.batch_alter_table('watchlist') as batch_op:
        batch_op.drop_constraint('uq_watchlist_user_stock', type_='unique')
