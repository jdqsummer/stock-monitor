# stock-monitor/backend/services/refresh_svc.py
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.westock_client import WestockClient
from backend.models.stock import StockSnapshot, WatchlistItem
from backend.schemas.stock import StockQuote

logger = logging.getLogger(__name__)


class RefreshService:
    """定时刷新：第三方渠道 → A 表"""

    @staticmethod
    async def collect_watchlist_codes(db: AsyncSession) -> list[str]:
        """所有用户自选股代码（去重）"""
        rows = await db.execute(select(WatchlistItem.stock_code).distinct())
        return [r[0] for r in rows.all()]

    @staticmethod
    async def _upsert_quote(db: AsyncSession, quote: StockQuote) -> StockSnapshot:
        row = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code == quote.code))
        ).scalar_one_or_none()
        if row is None:
            row = StockSnapshot(code=quote.code, name=quote.name)
            db.add(row)
        row.name = quote.name
        row.current_price = quote.current_price
        row.change_pct = quote.change_pct
        row.total_market_cap = quote.total_market_cap
        row.pe_dynamic = quote.pe_dynamic
        row.total_shares = quote.total_shares
        row.update_time = quote.update_time
        row.updated_at = datetime.now()
        return row

    @staticmethod
    async def refresh_quotes(db: AsyncSession) -> int:
        """刷新全部自选股行情到 stock_snapshots；单只失败保留旧数据不中断"""
        codes = await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    quote = await client.fetch_quote(code)
                except Exception as e:
                    logger.warning(f"刷新行情失败 {code}: {e}")
                    continue
                await RefreshService._upsert_quote(db, quote)
                count += 1
            await db.commit()
        finally:
            await client.close()
        return count

    @staticmethod
    async def refresh_financials(
        db: AsyncSession, codes: list[str] | None = None,
    ) -> int:
        """刷新财报到 financials；单只失败保留旧数据不中断"""
        codes = codes or await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    fin = await client.fetch_financials(code)
                except Exception as e:
                    logger.warning(f"刷新财报失败 {code}: {e}")
                    continue
                await RefreshService._upsert_financial(db, fin)
                count += 1
            await db.commit()
        finally:
            await client.close()
        return count

    @staticmethod
    async def _upsert_financial(db: AsyncSession, fin):
        from backend.models.stock import FinancialRecord

        row = (
            await db.execute(
                select(FinancialRecord).where(
                    FinancialRecord.code == fin.code,
                    FinancialRecord.report_period == fin.report_period,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = FinancialRecord(code=fin.code, report_period=fin.report_period)
            db.add(row)
        row.revenue = fin.revenue
        row.net_profit_parent = fin.net_profit_parent
        row.net_profit_deducted = fin.net_profit_deducted
        row.roe = fin.roe
        row.is_official = fin.is_official
        row.updated_at = datetime.now()
        return row
