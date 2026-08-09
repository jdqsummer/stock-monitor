# stock-monitor/backend/services/stock_data_svc.py
import json
import logging

from backend.data.cache import TTL_QUOTE, CacheService
from backend.data.westock_client import WestockClient
from backend.schemas.stock import MarginResult, StockQuote, WatchlistBoardRow

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
