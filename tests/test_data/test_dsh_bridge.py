# stock-monitor/tests/test_data/test_dsh_bridge.py
"""DataBridge MCP server 测试：直接调工具函数（monkeypatch fetch_quote）无外部依赖。"""
import pytest

from backend.data import dsh_bridge


@pytest.mark.asyncio
async def test_get_stock_snapshot_returns_dict(monkeypatch):
    async def fake_quote(code):
        from backend.schemas.stock import StockQuote
        return StockQuote(code=code, name="贵州茅台", current_price=1700.0,
                          total_market_cap=21400.0, pe_dynamic=28.5)
    monkeypatch.setattr(dsh_bridge, "fetch_quote", fake_quote)
    snap = await dsh_bridge.get_stock_snapshot("600519")
    assert snap["code"] == "600519"
    assert snap["current_price"] == 1700.0
    assert snap["pe_dynamic"] == 28.5


@pytest.mark.asyncio
async def test_get_industry_pe_uses_anchor():
    pe = await dsh_bridge.get_industry_pe("白酒")
    assert isinstance(pe, dict)
    assert "pe_low" in pe and "pe_high" in pe
