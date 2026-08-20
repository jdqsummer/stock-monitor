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
    # 真实 RPT_F10_FINANCE_MAINFINADATA 响应：扣非字段是 KCFJCXSYJLR
    return {"result": {"data": [
        {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2026-06-30",
         "TOTALOPERATEREVE": 1.2e11, "PARENTNETPROFIT": 3.5e10,
         "KCFJCXSYJLR": 3.2e10, "ROEJQ": 15.5},
        {"SECUCODE": "600519.SH", "SECURITY_NAME_ABBR": "贵州茅台", "REPORT_DATE": "2025-12-31",
         "TOTALOPERATEREVE": 2.3e11, "PARENTNETPROFIT": 6.6e10,
         "KCFJCXSYJLR": 6.2e10, "ROEJQ": 30.0},
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
    reports = await provider.fetch_financials("600519")
    assert len(reports) == 2
    report = reports[0]
    assert report.report_period == "2026H1"
    assert report.net_profit_parent == pytest.approx(3.5e10 / 1e8)
    assert report.net_profit_deducted == pytest.approx(3.2e10 / 1e8)
    assert report.roe == pytest.approx(15.5)
    assert report.is_official is True
    assert reports[1].report_period == "2025FY"


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


# ── 港股 ──

def _hk_search_fixture() -> dict:
    # AH 股工商银行：同一条响应同时含 A 与 H 两行（MktNum 116 = 港股）
    return {"QuotationCodeTable": {"Data": [
        {"Code": "601398", "Name": "工商银行", "MktNum": "1", "SecurityTypeName": "A股"},
        {"Code": "01398", "Name": "工商银行", "MktNum": "116", "SecurityTypeName": "港股"},
    ]}}


def _hk_quote_fixture() -> dict:
    # 真实 push2 港股响应：价格类字段 ×1000 整数（f2=5320 即 5.320，3 位小数）；
    # 涨跌幅 f3/换手 f8/PE f115 仍为 ×100（f3=15 即 0.15%）
    return {"rc": 0, "data": {"total": 1, "diff": [
        {"f2": 5320, "f3": 15, "f4": 8, "f8": 20,
         "f12": "01398", "f13": 116, "f14": "工商银行",
         "f20": 1.8e12, "f21": 1.75e12, "f115": 550, "f167": 850, "f168": 20},
    ]}}


def _hk_financial_fixture() -> dict:
    return {"result": {"data": [
        {"SECUCODE": "01398.HK", "SECURITY_NAME_ABBR": "工商银行", "REPORT_DATE": "2026-06-30",
         "TOTALOPERATEREVE": 4.0e11, "PARENTNETPROFIT": 1.7e11,
         "KCFJCXSYJLR": 1.68e11, "ROEJQ": 11.5},
    ], "pages": 1}}


def _hk_basicinfo_fixture() -> dict:
    return {"result": {"data": [
        {"SECUCODE": "01398.HK", "SECURITY_NAME_ABBR": "工商银行", "EM2016": "银行"},
    ], "pages": 1}}


@pytest.mark.asyncio
async def test_eastmoney_search_includes_hk():
    """AH 股搜索同时返回 A 与 H 两条，代码/市场区分"""
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_hk_search_fixture())))
    results = await provider.search_stock("工商银行")
    assert {r.code for r in results} == {"601398", "01398.HK"}
    by_code = {r.code: r for r in results}
    assert by_code["601398"].market == "A"
    assert by_code["01398.HK"].market == "HK"


@pytest.mark.asyncio
async def test_eastmoney_quote_hk():
    """港股价格字段 ×1000 精度（f2=5320 → 5.32，而非 A 股的 ×100 → 53.2）"""
    provider = EastMoneyProvider(transport=httpx.MockTransport(_handler_factory(_hk_quote_fixture())))
    quote = await provider.fetch_quote("01398.HK")
    assert quote.code == "01398.HK"
    assert quote.market == "HK"
    assert quote.current_price == 5.32
    assert quote.change_pct == 0.15
    assert quote.change_amount == 0.008
    assert quote.pe_dynamic == 5.5
    assert quote.total_market_cap == pytest.approx(1.8e12 / 1e8)


@pytest.mark.asyncio
async def test_eastmoney_financials_hk_secucode():
    """港股财报 secucode 直接用 01398.HK（不拼 .SH/.SZ）"""
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["filter"] = request.url.params["filter"]
        return httpx.Response(200, json=_hk_financial_fixture())

    provider = EastMoneyProvider(transport=httpx.MockTransport(handler))
    reports = await provider.fetch_financials("01398.HK")
    assert len(reports) == 1
    assert reports[0].report_period == "2026H1"
    # 精确断言 filter 用港股原 code，而非错误拼成 01398.HK.SZ
    assert captured["filter"] == '(SECUCODE="01398.HK")'
    assert "01398.HK.SZ" not in captured["url"]


@pytest.mark.asyncio
async def test_eastmoney_industry_hk_secucode():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["filter"] = request.url.params["filter"]
        return httpx.Response(200, json=_hk_basicinfo_fixture())

    provider = EastMoneyProvider(transport=httpx.MockTransport(handler))
    assert await provider.fetch_industry("01398.HK") == "银行"
    # 精确断言 filter 用港股原 code，而非错误拼成 01398.HK.SZ
    assert captured["filter"] == '(SECUCODE="01398.HK")'
    assert "01398.HK.SZ" not in captured["url"]
