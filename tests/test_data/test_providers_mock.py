import pytest

from backend.config import settings
from backend.data.providers.base import ProviderError, normalize_code
from backend.data.providers.mock import MockProvider


def test_config_default_priority_is_mock():
    assert settings.DATA_PROVIDER_PRIORITY == "mock"


def test_normalize_code():
    assert normalize_code("600519") == ("sh600519", "1.600519")
    assert normalize_code("000001") == ("sz000001", "0.000001")
    assert normalize_code("300750") == ("sz300750", "0.300750")


@pytest.mark.asyncio
async def test_mock_quote():
    provider = MockProvider()
    quote = await provider.fetch_quote("600519")
    assert quote.code == "600519"
    assert quote.current_price == 50.0
    assert quote.total_market_cap == 800.0
    assert quote.pe_dynamic == 25.0


@pytest.mark.asyncio
async def test_mock_financials():
    provider = MockProvider()
    reports = await provider.fetch_financials("600519")
    assert len(reports) == 8
    report = reports[0]
    assert report.report_period == "2026H1"
    assert report.net_profit_deducted == 32.0
    assert report.is_official is False
    assert reports[-1].report_period == "2024Q3"


@pytest.mark.asyncio
async def test_mock_news_empty():
    provider = MockProvider()
    assert await provider.fetch_news("600519") == []


@pytest.mark.asyncio
async def test_mock_search():
    provider = MockProvider()
    results = await provider.search_stock("600519")
    assert len(results) == 1
    assert results[0].code == "600519"
    assert results[0].name == "贵州茅台"
    assert await provider.search_stock("  ") == []


@pytest.mark.asyncio
async def test_mock_industry():
    provider = MockProvider()
    assert await provider.fetch_industry("600519") == "白酒"
    assert await provider.fetch_industry("000333") == "家电"
    with pytest.raises(ProviderError):
        await provider.fetch_industry("999999")  # 非 mock 库代码 → 无行业


@pytest.mark.asyncio
async def test_mock_search_hk_ah_dual():
    """AH 股工商银行：mock 库同时含 A(601398) 与 H(01398.HK)，搜索按名称命中两条"""
    provider = MockProvider()
    results = await provider.search_stock("工商银行")
    by_code = {r.code: r for r in results}
    assert "601398" in by_code
    assert "01398.HK" in by_code
    assert by_code["01398.HK"].market == "HK"


@pytest.mark.asyncio
async def test_mock_quote_hk():
    provider = MockProvider()
    quote = await provider.fetch_quote("00700.HK")
    assert quote.market == "HK"
    assert quote.name == "腾讯控股"
