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


@pytest.mark.asyncio
async def test_search_stock_returns_list_of_dicts(monkeypatch):
    """search_stock 输出必须是 list[dict]（FastMCP 1.28.1 结构化输出校验回归守护）。"""
    from backend.schemas.stock import StockQuote

    class FakeClient:
        async def search_stock(self, keyword):
            return [StockQuote(code="600519", name="贵州茅台", current_price=1700.0,
                               total_market_cap=21400.0, pe_dynamic=28.5)]

    monkeypatch.setattr(dsh_bridge, "_westock", FakeClient())  # _client() 直接返回该全局
    results = await dsh_bridge.search_stock("600519")

    assert isinstance(results, list)
    assert len(results) == 1
    assert all(isinstance(r, dict) for r in results)
    assert results[0] == {
        "code": "600519", "name": "贵州茅台", "current_price": 1700.0,
        "total_market_cap": 21400.0, "pe_dynamic": 28.5,
    }


@pytest.mark.asyncio
async def test_get_financials_returns_list_of_dicts(monkeypatch):
    """get_financials 输出必须是 list[dict] 且 periods 截断正确（回归守护）。"""
    from backend.schemas.stock import FinancialReport

    reports = [
        FinancialReport(code="600519", name="贵州茅台", report_period=f"202{i}H1",
                        revenue=100.0, net_profit_parent=74.0, net_profit_deducted=73.0)
        for i in range(10)
    ]

    class FakeClient:
        async def fetch_financials(self, code):
            return reports

    monkeypatch.setattr(dsh_bridge, "_westock", FakeClient())
    rows = await dsh_bridge.get_financials("600519", periods=8)

    assert isinstance(rows, list)
    assert len(rows) == 8                      # 10 条输入 → periods=8 截断
    assert all(isinstance(r, dict) for r in rows)
    assert set(rows[0].keys()) == {"report_period", "revenue",
                                   "net_profit_parent", "net_profit_deducted"}
    assert rows[0]["report_period"] == "2020H1"   # 保序：保留前 8 条
