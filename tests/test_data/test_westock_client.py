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
        """开发模式：模拟搜索返回 mock 库匹配结果（代码精确）"""
        results = await westock_client.search_stock("600519")
        assert len(results) == 1
        assert results[0].code == "600519"
        assert results[0].name == "贵州茅台"
        assert results[0].current_price == 1560.0

    @pytest.mark.asyncio
    async def test_search_by_name_fuzzy(self, westock_client):
        """名称模糊匹配"""
        results = await westock_client.search_stock("茅台")
        assert any(r.name == "贵州茅台" for r in results)

    @pytest.mark.asyncio
    async def test_search_no_match(self, westock_client):
        """无匹配返回空列表"""
        results = await westock_client.search_stock("不存在的股票")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_multiple_name_matches(self, westock_client):
        """名称匹配多只股票"""
        results = await westock_client.search_stock("中国")
        codes = {r.code for r in results}
        assert "601318" in codes  # 中国平安
        assert "601857" in codes  # 中国石油

    @pytest.mark.asyncio
    async def test_search_empty_keyword(self, westock_client):
        """空关键字返回空列表"""
        results = await westock_client.search_stock("  ")
        assert results == []
