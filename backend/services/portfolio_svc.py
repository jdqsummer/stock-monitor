# stock-monitor/backend/services/portfolio_svc.py
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.portfolio import Position

logger = logging.getLogger(__name__)


class DuplicatePositionError(Exception):
    """持仓已存在"""
    pass


# 部分更新哨兵：字段默认落在 _UNSET 表示「本次未传，保留旧值」；
# 显式传 None 表示「置空」（与未传严格区分）
_UNSET = object()


class PortfolioService:
    @staticmethod
    async def list_positions(db: AsyncSession, user_id: str) -> list[Position]:
        result = await db.execute(
            select(Position).where(Position.user_id == user_id)
            .order_by(Position.updated_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_position(
        db: AsyncSession, user_id: str, code: str, name: str, industry: str | None = None,
    ) -> Position:
        exists = await db.execute(select(Position).where(
            Position.user_id == user_id, Position.stock_code == code))
        if exists.scalar_one_or_none():
            raise DuplicatePositionError(f"该股票已在持仓中: {code} {name}")
        pos = Position(user_id=user_id, stock_code=code, stock_name=name, industry=industry,
                       shares=None, cost_price=None, purchased_at=None)
        db.add(pos)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise DuplicatePositionError(f"该股票已在持仓中: {code} {name}")
        await db.refresh(pos)
        return pos

    @staticmethod
    async def get_position(db: AsyncSession, user_id: str, position_id: str) -> Position | None:
        return (await db.execute(select(Position).where(
            Position.id == position_id, Position.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def update_position(
        db: AsyncSession, user_id: str, position_id: str,
        shares: float | None = _UNSET, cost_price: float | None = _UNSET,
        purchased_at: datetime | None = _UNSET,
    ) -> Position | None:
        """部分更新：只更新显式传入的字段（未传字段落在 _UNSET → 保留旧值；显式传 None → 置空）。"""
        pos = await PortfolioService.get_position(db, user_id, position_id)
        if pos is None:
            return None
        if shares is not _UNSET:
            pos.shares = shares
        if cost_price is not _UNSET:
            pos.cost_price = cost_price
        if purchased_at is not _UNSET:
            pos.purchased_at = purchased_at
        await db.commit()
        await db.refresh(pos)
        return pos

    @staticmethod
    async def remove_position(db: AsyncSession, user_id: str, position_id: str) -> bool:
        pos = await PortfolioService.get_position(db, user_id, position_id)
        if pos is None:
            return False
        await db.delete(pos)
        await db.commit()
        return True
