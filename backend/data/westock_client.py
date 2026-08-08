# stock-monitor/backend/data/westock_client.py
import logging
from typing import Optional

import httpx

from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


class WestockClientError(Exception):
    """westock-mcp 客户端异常"""
    pass


class WestockClient:
    """
    westock-mcp 客户端封装。

    使用 westock-mcp 的 MCP 工具接口获取行情/财报/新闻数据。
    如果 MCP 工具不可用，降级为模拟数据（开发阶段）。
    生产环境通过 MCP 协议调用 westock-mcp server。
    """

    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def fetch_quote(self, code: str) -> StockQuote:
        """
        获取实时行情。

        westock-mcp tool: get_stock_quote
        """
        client = await self._get_client()
        try:
            # 生产路径：调用 westock-mcp
            if self.base_url:
                resp = await client.post(
                    f"{self.base_url}/mcp/westock/quote",
                    json={"code": code},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return StockQuote(**data)

            # 开发阶段降级
            logger.warning(f"westock-mcp 未配置，返回模拟数据 for {code}")
            return self._mock_quote(code)

        except httpx.HTTPError as e:
            logger.error(f"获取行情失败 {code}: {e}")
            raise WestockClientError(f"行情获取失败: {e}") from e

    async def fetch_financials(self, code: str) -> FinancialReport:
        """
        获取最新财报。

        westock-mcp tool: get_financial_report
        """
        client = await self._get_client()
        try:
            if self.base_url:
                resp = await client.post(
                    f"{self.base_url}/mcp/westock/financials",
                    json={"code": code},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return FinancialReport(**data)

            return self._mock_financials(code)

        except httpx.HTTPError as e:
            logger.error(f"获取财报失败 {code}: {e}")
            raise WestockClientError(f"财报获取失败: {e}") from e

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        """
        获取公司近期新闻。

        westock-mcp tool: search_company_news
        """
        client = await self._get_client()
        try:
            if self.base_url:
                resp = await client.post(
                    f"{self.base_url}/mcp/westock/news",
                    json={"code": code, "limit": limit},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                return [CompanyNews(**item) for item in resp.json()]

            return []

        except httpx.HTTPError as e:
            logger.error(f"获取新闻失败 {code}: {e}")
            return []

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        """搜索股票（代码或名称模糊匹配）"""
        client = await self._get_client()
        try:
            if self.base_url:
                resp = await client.post(
                    f"{self.base_url}/mcp/westock/search",
                    json={"keyword": keyword},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                return [StockQuote(**item) for item in resp.json()]

            return []

        except httpx.HTTPError as e:
            logger.error(f"搜索股票失败 '{keyword}': {e}")
            return []

    def _mock_quote(self, code: str) -> StockQuote:
        """开发阶段模拟行情数据"""
        return StockQuote(
            code=code,
            name=f"模拟股票{code}",
            current_price=50.0,
            change_pct=1.5,
            total_market_cap=800.0,
            pe_dynamic=25.0,
            total_shares=16.0,
        )

    def _mock_financials(self, code: str) -> FinancialReport:
        """开发阶段模拟财报数据"""
        return FinancialReport(
            code=code,
            name=f"模拟股票{code}",
            report_period="2026H1",
            revenue=120.0,
            net_profit_parent=35.0,
            net_profit_deducted=32.0,
            roe=15.5,
            is_official=False,
        )

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
