# stock-monitor/backend/data/westock_client.py
import logging
from typing import Optional

import httpx

from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote

logger = logging.getLogger(__name__)


# 模块级 mock 股票库（开发阶段，未配置 westock-mcp 时用于搜索演示）
# (code, name, price, change_pct, total_market_cap亿, pe_dynamic, total_shares亿)
_MOCK_STOCK_DB: list[tuple] = [
    ("600519", "贵州茅台", 1560.0, 1.2, 19500.0, 25.3, 12.6),
    ("600036", "招商银行", 32.5, -0.3, 8200.0, 5.8, 252.2),
    ("601318", "中国平安", 45.8, 0.8, 8350.0, 9.1, 182.1),
    ("000858", "五粮液", 142.0, 1.0, 5510.0, 18.4, 38.8),
    ("000333", "美的集团", 55.0, 0.5, 3850.0, 12.0, 70.0),
    ("601899", "紫金矿业", 18.2, -1.0, 4800.0, 15.2, 263.2),
    ("600030", "中信证券", 21.5, 0.4, 3180.0, 14.0, 148.0),
    ("601012", "隆基绿能", 17.8, 2.1, 1350.0, 22.5, 75.8),
    ("002594", "比亚迪", 240.0, 1.8, 6980.0, 28.0, 29.1),
    ("000651", "格力电器", 40.5, -0.6, 2280.0, 8.5, 56.3),
    ("600276", "恒瑞医药", 45.2, 0.9, 2880.0, 32.0, 63.7),
    ("601857", "中国石油", 8.9, 0.2, 16280.0, 10.5, 1830.0),
]


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

            return self._mock_search(keyword)

        except httpx.HTTPError as e:
            logger.error(f"搜索股票失败 '{keyword}': {e}")
            return []

    def _mock_search(self, keyword: str) -> list[StockQuote]:
        """开发阶段：在内置 mock 股票库中按代码/名称匹配，代码精确优先"""
        kw = keyword.strip()
        if not kw:
            return []
        code_matches = [s for s in _MOCK_STOCK_DB if s[0] == kw]
        name_matches = [s for s in _MOCK_STOCK_DB if kw in s[1] and s not in code_matches]
        ordered = code_matches + name_matches
        return [
            StockQuote(
                code=s[0], name=s[1], current_price=s[2], change_pct=s[3],
                total_market_cap=s[4], pe_dynamic=s[5], total_shares=s[6],
            )
            for s in ordered
        ]

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
