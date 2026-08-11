# stock-monitor/backend/data/providers/mock.py
"""Mock 数据源：未配置真实渠道时的降级兜底（开发/离线可用）"""
from backend.data.providers.base import StockDataProvider
from backend.schemas.stock import CompanyNews, FinancialReport, StockQuote


# 内置 mock 股票库（开发演示用）
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


class MockProvider(StockDataProvider):
    """开发阶段模拟数据源"""

    async def fetch_quote(self, code: str) -> StockQuote:
        return self._mock_quote(code)

    async def fetch_financials(self, code: str) -> FinancialReport:
        return self._mock_financials(code)

    async def fetch_news(self, code: str, limit: int = 10) -> list[CompanyNews]:
        return []

    async def search_stock(self, keyword: str) -> list[StockQuote]:
        return self._mock_search(keyword)

    def _mock_search(self, keyword: str) -> list[StockQuote]:
        kw = keyword.strip()
        if not kw:
            return []
        code_matches = [s for s in _MOCK_STOCK_DB if s[0] == kw]
        name_matches = [s for s in _MOCK_STOCK_DB if kw in s[1] and s not in code_matches]
        return [
            StockQuote(code=s[0], name=s[1], current_price=s[2], change_pct=s[3],
                       total_market_cap=s[4], pe_dynamic=s[5], total_shares=s[6])
            for s in code_matches + name_matches
        ]

    def _mock_quote(self, code: str) -> StockQuote:
        return StockQuote(
            code=code, name=f"模拟股票{code}", current_price=50.0,
            change_pct=1.5, total_market_cap=800.0, pe_dynamic=25.0, total_shares=16.0,
        )

    def _mock_financials(self, code: str) -> FinancialReport:
        return FinancialReport(
            code=code, name=f"模拟股票{code}", report_period="2026H1",
            revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0,
            roe=15.5, is_official=False,
        )
