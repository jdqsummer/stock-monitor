import pytest

from backend.data.providers.base import ProviderError
from backend.data.providers.eastmoney import EastMoneyProvider
from backend.data.providers.mock import MockProvider
from backend.data.providers.tencent import TencentProvider
from backend.data.westock_client import WestockClient
from backend.schemas.stock import StockQuote


def test_build_chain_mock_always_appended():
    from backend.data.providers import build_provider_chain
    chain = build_provider_chain("tencent,eastmoney")
    assert [type(p) for p in chain] == [TencentProvider, EastMoneyProvider, MockProvider]
    chain2 = build_provider_chain("tencent,eastmoney,mock")
    assert [type(p) for p in chain2] == [TencentProvider, EastMoneyProvider, MockProvider]


def test_build_chain_unknown_skipped():
    from backend.data.providers import build_provider_chain
    chain = build_provider_chain("foo,tencent")
    assert [type(p) for p in chain] == [TencentProvider, MockProvider]


@pytest.mark.asyncio
async def test_facade_default_priority_is_mock():
    client = WestockClient()
    quote = await client.fetch_quote("600519")
    assert quote.current_price == 50.0  # MockProvider 兜底
    await client.close()


@pytest.mark.asyncio
async def test_facade_failover_tencent_down_to_eastmoney(monkeypatch):
    async def tencent_boom(self, code):
        raise ProviderError("tencent down")
    monkeypatch.setattr(TencentProvider, "fetch_quote", tencent_boom)

    async def em_ok(self, code):
        return StockQuote(code=code, name="东财行情", current_price=1.0, total_market_cap=1.0)
    monkeypatch.setattr(EastMoneyProvider, "fetch_quote", em_ok)

    client = WestockClient(priority="tencent,eastmoney")
    quote = await client.fetch_quote("600519")
    assert quote.name == "东财行情"
    await client.close()


@pytest.mark.asyncio
async def test_facade_all_fail_falls_to_mock(monkeypatch):
    async def boom(self, code):
        raise ProviderError("down")
    monkeypatch.setattr(TencentProvider, "fetch_quote", boom)
    monkeypatch.setattr(EastMoneyProvider, "fetch_quote", boom)

    client = WestockClient(priority="tencent,eastmoney")
    quote = await client.fetch_quote("600519")
    assert quote.current_price == 50.0  # mock 兜底
    await client.close()
