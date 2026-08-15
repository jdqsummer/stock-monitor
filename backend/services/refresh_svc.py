# stock-monitor/backend/services/refresh_svc.py
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.westock_client import WestockClient
from backend.db.database import async_session_factory
from backend.models.stock import StockSnapshot, WatchlistItem
from backend.services.analysis_job_svc import analysis_job_service
from backend.services.watchlist_svc import WatchlistService
from backend.schemas.stock import FinancialReport, StockQuote

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
        """刷新财报到 financials（多期逐条 upsert）；单只失败保留旧数据不中断"""
        codes = codes or await RefreshService.collect_watchlist_codes(db)
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    fin_list = await client.fetch_financials(code)
                except Exception as e:
                    logger.warning(f"刷新财报失败 {code}: {e}")
                    continue
                for fin in fin_list:
                    await RefreshService._upsert_financial(db, fin)
                count += len(fin_list)
            await db.commit()
        finally:
            await client.close()
        return count

    @staticmethod
    async def _upsert_financial(db: AsyncSession, fin: FinancialReport):
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

    @staticmethod
    async def recompute_analysis(db: AsyncSession) -> int:
        """收盘后重算：对每个 B 快照，用 A 表最新价重算 distance/signal"""
        from backend.models.stock import AnalysisSnapshot
        from backend.services.stock_data_svc import StockDataService

        snapshots = (
            await db.execute(select(AnalysisSnapshot))
        ).scalars().all()
        count = 0
        for snap in snapshots:
            quote_row = (
                await db.execute(select(StockSnapshot).where(StockSnapshot.code == snap.stock_code))
            ).scalar_one_or_none()
            if quote_row is None:
                continue
            quote = StockQuote(
                code=quote_row.code, name=quote_row.name,
                current_price=quote_row.current_price, change_pct=quote_row.change_pct,
                total_market_cap=quote_row.total_market_cap,
                pe_dynamic=quote_row.pe_dynamic, total_shares=quote_row.total_shares,
            )
            distance_pct, signal = StockDataService.recompute_distance_signal(snap, quote)
            snap.current_price = quote.current_price
            snap.current_market_cap = quote.total_market_cap
            snap.distance_pct = distance_pct
            snap.signal = signal.value
            count += 1
        await db.commit()
        return count


async def run_quote_refresh() -> int:
    """定时任务入口：独立 session 刷新行情"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.refresh_quotes(session)
        finally:
            await session.close()


async def collect_quote_refresh_users(db: AsyncSession) -> list[tuple[str, object]]:
    """返回 (user_id, interval_minutes 原始值)：仅有自选股的用户，间隔取配置默认 30。

    间隔不在此解析（脏数据如非数字/None 可能抛异常并沿 collect_func → sync →
    lifespan 传播导致启动失败）；原始值交由 sync_quote_refresh_jobs 统一校验。
    """
    from backend.models.user import User
    users = (await db.execute(select(User))).scalars().all()
    result = []
    for u in users:
        items = await WatchlistService.list_items(db, u.id)
        if not items:
            continue
        cfg = u.config or {}
        result.append((u.id, cfg.get("data_refresh_interval_minutes", 30)))
    return result


async def run_user_quote_refresh(user_id: str) -> int:
    """刷新单个用户的自选股行情到 A 表（幂等 upsert，单只失败不中断）"""
    async with async_session_factory() as session:
        items = await WatchlistService.list_items(session, user_id)
        codes = [it.stock_code for it in items]
        if not codes:
            return 0
        client = WestockClient()
        count = 0
        try:
            for code in codes:
                try:
                    quote = await client.fetch_quote(code)
                except Exception as e:
                    logger.warning(f"刷新行情失败 {code}: {e}")
                    continue
                await RefreshService._upsert_quote(session, quote)
                count += 1
            await session.commit()
        finally:
            await client.close()
        return count


async def collect_auto_analysis_users(db: AsyncSession) -> list[tuple[str, str]]:
    """返回 (user_id, 收盘时间) 列表：仅 analysis_auto_enabled=true 的用户"""
    from backend.models.user import User

    users = (await db.execute(select(User))).scalars().all()
    result = []
    for u in users:
        cfg = u.config or {}
        if cfg.get("analysis_auto_enabled"):
            result.append((u.id, cfg.get("analysis_schedule_afternoon", "16:00")))
    return result


async def run_user_auto_analysis(user_id: str, session_factory=None) -> int:
    """定时入口：收集该用户自选股 → 提交 scheduled job（读配置并发），返回数量"""
    from backend.models.user import User

    factory = session_factory or async_session_factory
    async with factory() as session:
        items = await WatchlistService.list_items(session, user_id)
        # session 块内提取纯列值，避免关闭后访问 ORM 对象
        codes = [it.stock_code for it in items]
        user = await session.get(User, user_id)
        cfg = (user.config or {}) if user else {}
        concurrency = int(cfg.get("analysis_concurrency", 3))
    if codes:
        analysis_job_service.submit(user_id, codes, source="scheduled", concurrency=concurrency)
    return len(codes)


async def run_recompute_analysis() -> int:
    """定时任务入口：独立 session 收盘重算 B 表"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.recompute_analysis(session)
        finally:
            await session.close()


async def run_financials_refresh() -> int:
    """定时任务入口：独立 session 刷新财报多期落库"""
    async with async_session_factory() as session:
        try:
            return await RefreshService.refresh_financials(session)
        finally:
            await session.close()
