# stock-monitor/backend/services/stock_data_svc.py
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.cache import TTL_QUOTE, CacheService
from backend.data.westock_client import WestockClient
from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.schemas.stock import MarginResult, Signal, StockQuote, WatchlistBoardRow
from backend.services.margin_engine import MarginEngine
from backend.services.snapshot_svc import SnapshotService

logger = logging.getLogger(__name__)


class StockDataService:
    """
    股票数据服务。

    组合 WestockClient + CacheService，提供带缓存的数据获取
    以及监控看板行数据的组装。
    """

    def __init__(self, westock_client: WestockClient, cache: CacheService):
        self.westock = westock_client
        self.cache = cache

    async def get_quote_with_cache(self, code: str) -> StockQuote:
        """获取行情（带缓存）"""
        key = f"quote:{code}"

        async def fetch_and_cache():
            quote = await self.westock.fetch_quote(code)
            return quote.model_dump_json()

        data = await self.cache.get_or_set(key, TTL_QUOTE, fetch_and_cache)
        return StockQuote.model_validate_json(data)

    async def get_board_row(self, code: str, margin_result: MarginResult) -> WatchlistBoardRow:
        """组装监控看板行数据"""
        quote = await self.get_quote_with_cache(code)
        return WatchlistBoardRow(
            code=code,
            name=quote.name,
            annual_profit=f"{margin_result.annual_profit_low:.0f}-{margin_result.annual_profit_high:.0f}亿",
            profit_method=margin_result.profit_method,
            swing_pe=f"{margin_result.pe_low:.0f}-{margin_result.pe_high:.0f}倍",
            swing_market_cap=f"{margin_result.swing_market_cap_low:.0f}-{margin_result.swing_market_cap_high:.0f}亿",
            swing_price=f"{margin_result.swing_price_low:.0f}-{margin_result.swing_price_high:.0f}元",
            current_market_cap=margin_result.current_market_cap,
            current_price=margin_result.current_price,
            distance_pct=margin_result.distance_pct,
            signal=margin_result.signal,
            analysis_date=margin_result.data_date,
        )

    @staticmethod
    async def get_quote_for_code(db: AsyncSession, code: str) -> StockQuote | None:
        """优先读 A 表 stock_snapshots；无则实时拉取兜底"""
        row = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code == code))
        ).scalar_one_or_none()
        if row is not None:
            return StockQuote(
                code=row.code, name=row.name, current_price=row.current_price,
                change_pct=row.change_pct, total_market_cap=row.total_market_cap,
                pe_dynamic=row.pe_dynamic, total_shares=row.total_shares,
                update_time=row.update_time,
            )
        try:
            return await WestockClient().fetch_quote(code)
        except Exception:
            return None

    @staticmethod
    def recompute_distance_signal(
        snapshot: AnalysisSnapshot, quote: StockQuote,
    ) -> tuple[float, Signal]:
        """用实时价重算距击球区与信号灯（击球区参数取快照）"""
        swing_high = snapshot.swing_price_high
        if swing_high and swing_high > 0:
            distance_frac = (quote.current_price - swing_high) / swing_high
            distance_pct = round(distance_frac * 100, 1)
        else:
            distance_pct = 999.9          # 哨兵：击球区无效 → 高估区
            distance_frac = 999.9
        signal, _, _ = MarginEngine.determine_signal(distance_frac, snapshot.annual_profit_low)
        return distance_pct, signal

    @staticmethod
    def snapshot_to_dict(snapshot: AnalysisSnapshot, quote: StockQuote | None) -> dict:
        """B 表快照 → 详情 dict（含定性字段；risk/warnings 解析为列表）"""
        name = quote.name if quote else ""
        return {
            "code": snapshot.stock_code,
            "name": name,
            "annual_profit": f"{snapshot.annual_profit_low:.0f}-{snapshot.annual_profit_high:.0f}亿",
            "profit_method": snapshot.profit_method,
            "swing_pe": f"{snapshot.pe_low:.0f}-{snapshot.pe_high:.0f}倍",
            "swing_market_cap": f"{snapshot.swing_market_cap_low:.0f}-{snapshot.swing_market_cap_high:.0f}亿",
            "swing_price": f"{snapshot.swing_price_low:.0f}-{snapshot.swing_price_high:.0f}元",
            "current_market_cap": snapshot.current_market_cap,
            "current_price": snapshot.current_price,
            "distance_pct": snapshot.distance_pct,
            "signal": snapshot.signal,
            "signal_label": snapshot.signal_label,
            "industry": snapshot.industry_category,
            "industry_category": snapshot.industry_category,
            "analysis_date": snapshot.data_date.isoformat() if snapshot.data_date else None,
            "analysis_source": snapshot.analysis_source,
            "analysis_completed_at": (
                snapshot.analysis_completed_at.isoformat() if snapshot.analysis_completed_at else None
            ),
            "moat_assessment": snapshot.moat_assessment,
            "risk_factors": json.loads(snapshot.risk_factors) if snapshot.risk_factors else [],
            "pe_rationale": snapshot.pe_rationale,
            "recommendation": snapshot.recommendation,
            "profit_quality_ok": snapshot.profit_quality_ok,
            "profit_quality_warnings": (
                json.loads(snapshot.profit_quality_warnings) if snapshot.profit_quality_warnings else []
            ),
        }

    @staticmethod
    async def get_board_rows(
        db: AsyncSession, user_id: str, items,
    ) -> list[WatchlistBoardRow]:
        """组装安全边际监控看板行：A.watchlist × B.snapshot × A 实时价（批量查询，避免 N+1）"""
        rows: list[WatchlistBoardRow] = []
        if not items:
            return rows

        codes = [item.stock_code for item in items]
        # 批量取 A 表行情
        a_rows = (
            await db.execute(select(StockSnapshot).where(StockSnapshot.code.in_(codes)))
        ).scalars().all()
        quotes_by_code: dict[str, StockQuote] = {}
        for a in a_rows:
            quotes_by_code[a.code] = StockQuote(
                code=a.code, name=a.name, current_price=a.current_price,
                change_pct=a.change_pct, total_market_cap=a.total_market_cap,
                pe_dynamic=a.pe_dynamic, total_shares=a.total_shares,
                update_time=a.update_time,
            )
        # 批量取 B 表快照
        snap_rows = (
            await db.execute(
                select(AnalysisSnapshot).where(
                    AnalysisSnapshot.user_id == user_id,
                    AnalysisSnapshot.stock_code.in_(codes),
                )
            )
        ).scalars().all()
        snapshots_by_code: dict[str, AnalysisSnapshot] = {
            s.stock_code: s for s in snap_rows
        }

        for item in items:
            quote = quotes_by_code.get(item.stock_code)
            if quote is None:
                # A 表无该 code → 兜底取实时行情
                quote = await StockDataService.get_quote_for_code(db, item.stock_code)
            if quote is None:
                continue
            snapshot = snapshots_by_code.get(item.stock_code)
            if snapshot is None:
                rows.append(WatchlistBoardRow(
                    code=item.stock_code, name=item.stock_name,
                    annual_profit="", profit_method="", swing_pe="",
                    swing_market_cap="", swing_price="",
                    current_market_cap=quote.total_market_cap,
                    current_price=quote.current_price,
                    distance_pct=None, signal=Signal.NONE,
                    industry=item.industry, analysis_date=None,
                ))
                continue
            distance_pct, signal = StockDataService.recompute_distance_signal(snapshot, quote)
            rows.append(WatchlistBoardRow(
                code=item.stock_code,
                name=quote.name or item.stock_name,
                annual_profit=f"{snapshot.annual_profit_low:.0f}-{snapshot.annual_profit_high:.0f}亿",
                profit_method=snapshot.profit_method,
                swing_pe=f"{snapshot.pe_low:.0f}-{snapshot.pe_high:.0f}倍",
                swing_market_cap=f"{snapshot.swing_market_cap_low:.0f}-{snapshot.swing_market_cap_high:.0f}亿",
                swing_price=f"{snapshot.swing_price_low:.0f}-{snapshot.swing_price_high:.0f}元",
                current_market_cap=quote.total_market_cap,
                current_price=quote.current_price,
                distance_pct=distance_pct,
                signal=signal,
                industry=item.industry,
                analysis_date=snapshot.data_date,
            ))
        return rows
