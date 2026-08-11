# stock-monitor/backend/data/westock_client.py
"""市场数据客户端门面：持多渠道 provider 链，主备自动切换，永不阻断。

调用方（data_agent / workflow / watchlist / refresh / stock_data_svc）只依赖本类，
public 方法签名保持不变。数据源优先级由 DATA_PROVIDER_PRIORITY 配置。
"""
import logging

from backend.data.providers import build_provider_chain
from backend.data.providers.base import ProviderError, StockDataProvider
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class WestockClient:
    """按优先级链依次尝试各数据源，全部失败时回退 MockProvider"""

    def __init__(self, priority: str | None = None):
        self.providers: list[StockDataProvider] = build_provider_chain(priority)

    async def fetch_quote(self, code: str) -> StockQuote:
        last_error: Exception | None = None
        for p in self.providers:
            try:
                return await p.fetch_quote(code)
            except ProviderError as e:
                logger.warning(f"数据源 {type(p).__name__} 行情失败: {e}")
                last_error = e
        raise ProviderError(f"所有数据源均不可用: {code}: {last_error}")

    async def fetch_financials(self, code: str) -> FinancialReport:
        last_error: Exception | None = None
        for p in self.providers:
            try:
                return await p.fetch_financials(code)
            except ProviderError as e:
                logger.warning(f"数据源 {type(p).__name__} 财报失败: {e}")
                last_error = e
        raise ProviderError(f"所有数据源财报均不可用: {code}: {last_error}")

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        for p in self.providers:
            try:
                news = await p.fetch_news(code, limit)
                if news:
                    return news
            except ProviderError as e:
                logger.warning(f"数据源 {type(p).__name__} 新闻失败: {e}")
                continue
        return []

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        for p in self.providers:
            try:
                results = await p.search_stock(keyword)
                if results:
                    return results
            except ProviderError as e:
                logger.warning(f"数据源 {type(p).__name__} 搜索失败: {e}")
                continue
        return []

    async def close(self):
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass
