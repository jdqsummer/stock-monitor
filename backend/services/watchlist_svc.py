# stock-monitor/backend/services/watchlist_svc.py
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.providers.base import ProviderError
from backend.data.westock_client import WestockClient
from backend.models.stock import WatchlistItem


class DuplicateStockError(Exception):
    """自选股已存在"""
    pass


# 内置代码 → 行业映射（智能分类数据源；覆盖 mock 库股票）
_INDUSTRY_MAP = {
    "600519": "白酒",
    "000858": "白酒",
    "600036": "银行",
    "601318": "保险",
    "000333": "家电",
    "000651": "家电",
    "601899": "有色金属",
    "600030": "非银金融",
    "601012": "光伏",
    "002594": "汽车",
    "600276": "医药生物",
    "601857": "石油石化",
}


class WatchlistService:
    @staticmethod
    async def list_items(db: AsyncSession, user_id: str) -> list[WatchlistItem]:
        result = await db.execute(
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.added_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_item(
        db: AsyncSession, user_id: str, code: str, name: str, industry: str | None = None,
    ) -> WatchlistItem:
        # 去重：同用户 + 同代码
        exists = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.stock_code == code,
            )
        )
        if exists.scalar_one_or_none():
            raise DuplicateStockError(f"该股票已在自选股中: {code} {name}")

        item = WatchlistItem(
            user_id=user_id,
            stock_code=code,
            stock_name=name,
            industry=industry,
        )
        db.add(item)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise DuplicateStockError(f"该股票已在自选股中: {code} {name}")
        await db.refresh(item)
        return item

    @staticmethod
    async def remove_item(db: AsyncSession, user_id: str, item_id: str) -> bool:
        result = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.id == item_id,
                WatchlistItem.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        await db.delete(item)
        await db.commit()
        return True

    @staticmethod
    async def update_industry(
        db: AsyncSession, user_id: str, item_id: str, industry: str | None,
    ) -> WatchlistItem | None:
        result = await db.execute(
            select(WatchlistItem).where(
                WatchlistItem.id == item_id,
                WatchlistItem.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        item.industry = industry
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def auto_classify(
        db: AsyncSession, user_id: str, client: WestockClient | None = None,
    ) -> int:
        """智能分类：只为未分类（industry 为空）的自选股填行业。

        内置代码→行业映射优先（离线快路径），未收录代码经数据源链补全；
        已手动分类的股票不覆盖。返回更新数量。
        """
        items = await WatchlistService.list_items(db, user_id)
        updated = 0
        for item in items:
            if item.industry:
                continue  # 已分类（含手动），保留不覆盖
            industry = _INDUSTRY_MAP.get(item.stock_code)  # 离线快路径（覆盖 mock 库）
            if not industry and client:
                try:
                    industry = await client.fetch_industry(item.stock_code)
                except ProviderError:
                    industry = None  # 数据源不可用 → 跳过该股，不阻断整批
            if industry:
                item.industry = industry
                updated += 1
        if updated:
            await db.commit()
        return updated
