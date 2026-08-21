import httpx
import pytest

from backend.data.providers.base import ProviderError
from backend.data.providers.tencent import TencentProvider
from backend.schemas.stock import StockQuote


def _quote_fixture() -> str:
    """构造 qt.gtimg.cn 响应（GBK 文本，~ 分隔，字段索引按文档）"""
    fields = [""] * 60
    fields[1] = "贵州茅台"
    fields[2] = "600519"
    fields[3] = "1720.00"
    fields[4] = "1718.00"
    fields[5] = "1701.00"
    fields[30] = "20260811150000"
    fields[31] = "2.06"
    fields[32] = "0.12"
    fields[38] = "0.20"
    fields[39] = "25.30"
    fields[44] = "19450.00"
    fields[45] = "19500.00"
    return ('v_sh600519="' + "~".join(fields) + '";')


def _search_fixture() -> str:
    return (
        'var cb_=({q:"茅台",v:"sh600519~贵州茅台~1~gt_贵州茅台~茅台;'
        'sz000001~平安银行~1~gt_平安银行~平安;sh000001~上证指数~7~gt_上证指数~上证"});'
    )


def _handler_factory(body: str, encoding: str = "gbk"):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode(encoding))
    return handler


@pytest.mark.asyncio
async def test_tencent_quote():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_quote_fixture())))
    quote = await provider.fetch_quote("600519")
    assert isinstance(quote, StockQuote)
    assert quote.code == "600519"
    assert quote.name == "贵州茅台"
    assert quote.current_price == 1720.0
    assert quote.change_pct == 0.12
    assert quote.change_amount == 2.06
    assert quote.total_market_cap == 19500.0
    assert quote.turnover_rate == 0.20
    assert quote.pe_dynamic == 25.3
    assert quote.total_shares == pytest.approx(19500.0 / 1720.0)


@pytest.mark.asyncio
async def test_tencent_quote_http_error_raises_provider_error():
    async def handler(request):
        return httpx.Response(500)
    provider = TencentProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        await provider.fetch_quote("600519")


@pytest.mark.asyncio
async def test_tencent_quote_bad_format():
    async def handler(request):
        return httpx.Response(200, content="not-a-quote".encode("gbk"))
    provider = TencentProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        await provider.fetch_quote("600519")


@pytest.mark.asyncio
async def test_tencent_search():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_search_fixture())))
    results = await provider.search_stock("茅台")
    codes = {r.code for r in results}
    assert "sh600519" in codes
    assert "sz000001" in codes
    assert "sh000001" not in codes  # 指数排除


@pytest.mark.asyncio
async def test_tencent_search_empty_keyword():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_search_fixture())))
    assert await provider.search_stock("  ") == []


@pytest.mark.asyncio
async def test_tencent_industry_raises():
    """腾讯公开接口无稳定行业源，降级抛错由链切换到东财"""
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_quote_fixture())))
    with pytest.raises(ProviderError):
        await provider.fetch_industry("600519")


# ── 港股 ──

def _hk_search_fixture() -> str:
    # smartbox v 字段：parts[0]=带市场前缀 code，parts[1]=名称，parts[2]=类型（港股为 3）
    return (
        'var cb_=({q:"腾讯",v:"sh600519~贵州茅台~1~gt_贵州茅台;'
        'hk00700~腾讯控股~3~gt_腾讯控股;sh000001~上证指数~7~gt_上证指数"});'
    )


def _hk_quote_fixture() -> str:
    # 真实 qt.gtimg.cn 港股响应（len=78）：字段下标与 A 股镜像一致（[3]现价/[4]昨收/
    # [31]涨跌额/[32]涨跌幅/[39]PE/[45]市值），仅时间戳 [30] 为 "YYYY/MM/DD HH:MM:SS"
    # （19 位，A 股为 14 位数字）；[38] 换手港股不返回（0）。
    fields = [""] * 78
    fields[1] = "腾讯控股"
    fields[2] = "00700"
    fields[3] = "459.000"
    fields[4] = "451.400"
    fields[5] = "451.000"
    fields[30] = "2026/08/21 16:06:24"
    fields[31] = "7.600"
    fields[32] = "1.68"
    fields[38] = "0"
    fields[39] = "16.78"
    fields[44] = "41700.00"
    fields[45] = "41783.35"
    return ('v_hk00700="' + "~".join(fields) + '";')


@pytest.mark.asyncio
async def test_tencent_search_includes_hk():
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_hk_search_fixture())))
    results = await provider.search_stock("腾讯")
    by_code = {r.code: r for r in results}
    assert by_code["00700.HK"].market == "HK"
    assert by_code["sh600519"].market == "A"
    assert "sh000001" not in by_code  # 指数排除


@pytest.mark.asyncio
async def test_tencent_quote_hk():
    """港股行情 layout 已实测为 A 股镜像：腾讯直接解析港股行情（2026-08-21 生产验证）。

    qt.gtimg.cn 港股响应（len=78）字段下标与 A 股一致（[3]现价/[4]昨收/[31]涨跌额/
    [32]涨跌幅/[39]PE/[45]市值），仅时间戳格式不同（"YYYY/MM/DD HH:MM:SS" 19 位）。
    """
    provider = TencentProvider(transport=httpx.MockTransport(_handler_factory(_hk_quote_fixture())))
    quote = await provider.fetch_quote("00700.HK")
    assert quote.code == "00700.HK"
    assert quote.market == "HK"
    assert quote.current_price == 459.0
    assert quote.change_pct == 1.68
    assert quote.change_amount == 7.6
    assert quote.pe_dynamic == 16.78
    assert quote.total_market_cap == pytest.approx(41783.35)
    assert quote.turnover_rate is None  # 港股 [38] 无换手 → None
    assert quote.update_time is not None  # 港股时间戳 "2026/08/21 16:06:24" 已解析
