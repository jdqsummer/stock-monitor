# stock-monitor/tests/test_data/test_westock_client.py
import pytest

from backend.schemas.stock import StockQuote, FinancialReport, CompanyNews


class TestWestockClient:
    @pytest.mark.asyncio
    async def test_fetch_quote_mock(self, westock_client):
        """开发模式：模拟行情数据"""
        quote = await westock_client.fetch_quote("600519")
        assert isinstance(quote, StockQuote)
        assert quote.code == "600519"
        assert quote.current_price == 50.0
        assert quote.total_market_cap == 800.0
        assert quote.pe_dynamic == 25.0

    @pytest.mark.asyncio
    async def test_fetch_financials_mock(self, westock_client):
        """开发模式：模拟财报数据"""
        report = await westock_client.fetch_financials("600519")
        assert isinstance(report, FinancialReport)
        assert report.report_period == "2026H1"
        assert report.net_profit_deducted == 32.0
        assert report.is_official is False

    @pytest.mark.asyncio
    async def test_fetch_news_mock(self, westock_client):
        """开发模式：模拟新闻返回空列表"""
        news = await westock_client.fetch_news("600519")
        assert isinstance(news, list)
        assert len(news) == 0

    @pytest.mark.asyncio
    async def test_search_stock_mock(self, westock_client):
        """开发模式：模拟搜索返回空列表"""
        results = await westock_client.search_stock("茅台")
        assert isinstance(results, list)
        assert len(results) == 0
