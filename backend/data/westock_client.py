# stock-monitor/backend/data/westock_client.py
"""市场数据客户端门面：持多渠道 provider 链，主备自动切换，永不阻断。

调用方（data_agent / workflow / watchlist / refresh / stock_data_svc）只依赖本类，
public 方法签名保持不变。数据源优先级由 DATA_PROVIDER_PRIORITY 配置。
"""
import logging

from backend.data.providers import build_provider_chain
from backend.data.providers.base import ProviderError, StockDataProvider
from backend.data.providers.mock import MockProvider
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

    async def fetch_financials(self, code: str) -> list[FinancialReport]:
        # 财报是事实数据：仅当链为纯 mock（本地开发 mock 模式）时才允许 MockProvider 伪造财报；
        # 配置了真实数据源时跳过 MockProvider —— 真源无数据的股票（如东财 datacenter 无港股财报）
        # 诚实返回「无数据」（抛 ProviderError），不把伪造财报当生产事实。refresh/聊天工具据此降级。
        real_only = any(not isinstance(p, MockProvider) for p in self.providers)
        last_error: Exception | None = None
        for p in self.providers:
            if real_only and isinstance(p, MockProvider):
                continue
            try:
                reports = await p.fetch_financials(code)
                if reports:
                    return reports
                last_error = ProviderError(f"数据源 {type(p).__name__} 财报为空: {code}")
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

    async def fetch_industry(self, code: str) -> str:
        """按优先级链取行业分类，全部不可用时抛 ProviderError（服务层跳过不阻断）"""
        last_error: Exception | None = None
        for p in self.providers:
            try:
                industry = await p.fetch_industry(code)
                if industry:
                    return industry
            except ProviderError as e:
                logger.warning(f"数据源 {type(p).__name__} 行业失败: {e}")
                last_error = e
        raise ProviderError(f"所有数据源行业均不可用: {code}: {last_error}")

    async def close(self):
        for p in self.providers:
            try:
                await p.close()
            except Exception:
                pass
