import httpx
import pytest

from backend.data.providers.base import ProviderError
from backend.data.providers.eastmoney import EastMoneyProvider
from backend.schemas.stock import StockQuote


def _quote_fixture() -> dict:
    # 真实 push2 响应：价格类字段 ×100 整数（f2=172000 即 1720.00）
    return {
        "rc": 0, "data": {"total": 1, "diff": [
            {"f2": 172000, "f3": 12, "f4": 206, "f8": 20,
             "f12": "600519", "f13": 1, "f14": "贵州茅台",
             "f20": 2.16e12, "f21": 2.15e12, "f115": 2530, "f167": 850, "f168": 20},
        ]},
    }


def _search_fixture() -> dict:
    return {"QuotationCodeTable": {"Data": [
        {"Code": "600519", "Name": "贵州茅台", "MktNum": "1", "SecurityTypeName": "A股"},
        {"Code": "000858", "Name": "五粮液", "MktNum": "0", "SecurityTypeName": "A股"},
    ]}}


def _financial_fixture() -> dict:
    # 真实 RPT_F10_FINANCE_MAINFINADATA 响应：扣非字段是 KCFJCXSYJLR，
    # 而非 DEDUCTPARENTNETPROFIT（后者在该接口恒为 null）
    return {"result": {"data": [
        {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2026-06-30",
         "TOTALOPERATEREVE": 1.2e11, "PARENTNETPROFIT": 3.5e10,
         "KCFJCXSYJLR": 3.2e10, "ROEJQ": 15.5},
    ], "pages": 1}}


def _handler_factory(payload: dict):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    return handler


@pytest.mark.asyncio
async def test_eastmoney_quote():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_quote_fixture())))
    quote = await provider.fetch_quote("600519")
    assert isinstance(quote, StockQuote)
    assert quote.code == "600519"
    assert quote.name == "贵州茅台"
    assert quote.current_price == 1720.0
    assert quote.change_pct == 0.12
    assert quote.change_amount == 2.06
    assert quote.total_market_cap == pytest.approx(2.16e12 / 1e8)  # 元 → 亿
    assert quote.turnover_rate == 0.20
    assert quote.pe_dynamic == 25.3


@pytest.mark.asyncio
async def test_eastmoney_quote_no_data():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory({"data": {"diff": []}})))
    with pytest.raises(ProviderError):
        await provider.fetch_quote("600519")


@pytest.mark.asyncio
async def test_eastmoney_search():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_search_fixture())))
    results = await provider.search_stock("茅台")
    assert {r.code for r in results} == {"600519", "000858"}


@pytest.mark.asyncio
async def test_eastmoney_financials():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_financial_fixture())))
    report = await provider.fetch_financials("600519")
    assert report.report_period == "2026H1"
    assert report.net_profit_parent == pytest.approx(3.5e10 / 1e8)
    assert report.net_profit_deducted == pytest.approx(3.2e10 / 1e8)
    assert report.roe == pytest.approx(15.5)
    assert report.is_official is True


def _basicinfo_fixture() -> dict:
    # 东财 F10 基本资料：EM2016 为「一级-二级-三级」行业分类
    return {"result": {"data": [
        {"SECUCODE": "300750.SZ", "SECURITY_NAME_ABBR": "宁德时代",
         "EM2016": "电气设备-电源设备-储能设备"},
    ], "pages": 1}}


@pytest.mark.asyncio
async def test_eastmoney_industry():
    """返回完整 EM2016 链（一级-二级-三级），供细粒度 PE 锚定"""
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_basicinfo_fixture())))
    assert await provider.fetch_industry("300750") == "电气设备-电源设备-储能设备"


@pytest.mark.asyncio
async def test_eastmoney_industry_no_data():
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory({"result": {"data": []}})))
    with pytest.raises(ProviderError):
        await provider.fetch_industry("300750")


@pytest.mark.asyncio
async def test_eastmoney_industry_missing_em2016():
    provider = EastMoneyProvider(transport=httpx.MockTransport(
        _handler_factory({"result": {"data": [{"SECUCODE": "300750.SZ"}]}})))
    with pytest.raises(ProviderError):
        await provider.fetch_industry("300750")
