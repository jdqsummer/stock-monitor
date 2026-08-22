from unittest.mock import AsyncMock

import pytest
from datetime import date

from backend.models.stock import AnalysisSnapshot, StockSnapshot, WatchlistItem
from backend.schemas.stock import Signal, StockQuote
from backend.services.stock_data_svc import StockDataService


@pytest.mark.asyncio
async def test_recompute_distance_signal(db_session):
    snap = AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    )
    quote = StockQuote(code="600519", name="贵州茅台", current_price=2456.0,
                       total_market_cap=19500.0)
    distance, signal = StockDataService.recompute_distance_signal(snap, quote)
    assert distance == 0.0
    assert signal == Signal.GREEN


@pytest.mark.asyncio
async def test_recompute_distance_signal_invalid_swing(db_session):
    snap = AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=0, swing_price_high=0,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    )
    quote = StockQuote(code="600519", name="贵州茅台", current_price=1560.0,
                       total_market_cap=19500.0)
    distance, signal = StockDataService.recompute_distance_signal(snap, quote)
    assert distance == 999.9
    assert signal == Signal.RED


@pytest.mark.asyncio
async def test_get_board_rows_with_snapshot(db_session):
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                 total_market_cap=19500.0, pe_dynamic=25.3))
    db_session.add(AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    ))
    items = [WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台", industry="白酒")]
    await db_session.commit()

    rows = await StockDataService.get_board_rows(db_session, "u1", items)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "贵州茅台"
    assert row.annual_profit == "688-842亿"
    assert row.swing_price == "1147-2456元"
    assert row.industry == "白酒"
    assert row.signal == Signal.GREEN
    assert row.pe_dynamic == 25.3


@pytest.mark.asyncio
async def test_get_board_rows_without_snapshot(db_session):
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                 total_market_cap=19500.0, pe_dynamic=25.3))
    items = [WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台")]
    await db_session.commit()

    rows = await StockDataService.get_board_rows(db_session, "u1", items)
    assert len(rows) == 1
    assert rows[0].signal == Signal.NONE
    assert rows[0].distance_pct is None
    assert rows[0].pe_dynamic == 25.3


@pytest.mark.asyncio
async def test_get_board_rows_skips_when_no_quote(db_session, monkeypatch):
    items = [WatchlistItem(user_id="u1", stock_code="999999", stock_name="不存在")]
    await db_session.commit()

    async def boom(self, code):
        raise RuntimeError("no data")

    monkeypatch.setattr("backend.services.stock_data_svc.WestockClient.fetch_quote", boom)
    rows = await StockDataService.get_board_rows(db_session, "u1", items)
    assert rows == []


@pytest.mark.asyncio
async def test_get_board_rows_allow_live_false_skips_live_fallback(db_session, monkeypatch):
    """allow_live=False 时 A 表缺 code 不兜底实时拉取（聊天摘要只读快照），行被跳过"""
    items = [WatchlistItem(user_id="u1", stock_code="999999", stock_name="不存在")]
    await db_session.commit()

    live = AsyncMock(return_value=StockQuote(code="999999", name="实时", current_price=10.0,
                                            total_market_cap=100.0))
    monkeypatch.setattr(
        "backend.services.stock_data_svc.StockDataService.get_quote_for_code", live,
    )
    rows = await StockDataService.get_board_rows(db_session, "u1", items, allow_live=False)
    assert rows == []
    live.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_board_rows_allow_live_true_uses_live_fallback(db_session, monkeypatch):
    """allow_live=True（默认）时 A 表缺 code 走实时兜底"""
    items = [WatchlistItem(user_id="u1", stock_code="999999", stock_name="不存在")]
    await db_session.commit()

    live = AsyncMock(return_value=StockQuote(code="999999", name="实时", current_price=10.0,
                                            total_market_cap=100.0))
    monkeypatch.setattr(
        "backend.services.stock_data_svc.StockDataService.get_quote_for_code", live,
    )
    rows = await StockDataService.get_board_rows(db_session, "u1", items)
    assert len(rows) == 1
    assert rows[0].current_price == 10.0
    assert rows[0].signal == Signal.NONE
    live.assert_awaited_once()


def _min_snapshot() -> AnalysisSnapshot:
    """snapshot_to_dict 所需的完整数值字段快照（模型对象构造不触发 column default）"""
    return AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green",
    )


@pytest.mark.asyncio
async def test_snapshot_to_dict_includes_pe_dynamic():
    """snapshot_to_dict 输出动态 PE（A 表行情 quote 携带）"""
    quote = StockQuote(code="600519", name="贵州茅台", current_price=1560.0,
                       total_market_cap=19500.0, pe_dynamic=25.3)
    d = StockDataService.snapshot_to_dict(_min_snapshot(), quote)
    assert d["pe_dynamic"] == 25.3


@pytest.mark.asyncio
async def test_snapshot_to_dict_pe_dynamic_none_without_quote():
    """quote 为 None（无行情）时 pe_dynamic 输出 None，前端宽容渲染 —"""
    d = StockDataService.snapshot_to_dict(_min_snapshot(), None)
    assert d["pe_dynamic"] is None


@pytest.mark.asyncio
async def test_snapshot_to_dict_includes_sell_group():
    """Task 7: snapshot_to_dict 输出 sell 组格式化字符串与原始字段。"""
    snap = AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green",
        analysis_mode="position",
        sell_pe_low=30.0, sell_pe_high=35.0, sell_pe_rationale="疯狂卖出",
        sell_market_cap_low=960.0, sell_market_cap_high=1225.0,
        sell_price_low=76.0, sell_price_high=98.0,
        sell_distance_pct=38.2, sell_signal="red", sell_action="sell",
        sell_analysis='{"principles":{"price_crazy":{"triggered":true}}}',
        stage_results_sell='{"sell_analysis":{"sell_action":"sell"}}',
    )
    d = StockDataService.snapshot_to_dict(snap, None)
    assert d["analysis_mode"] == "position"
    assert d["sell_pe"] == "30-35倍"
    assert d["sell_market_cap"] == "960-1225亿"
    assert d["sell_price"] == "76-98元"
    assert d["sell_pe_rationale"] == "疯狂卖出"
    assert d["sell_distance_pct"] == 38.2
    assert d["sell_signal"] == "red"
    assert d["sell_action"] == "sell"
    assert d["sell_analysis"] == {"principles": {"price_crazy": {"triggered": True}}}
    assert d["stage_results_sell"] == {"sell_analysis": {"sell_action": "sell"}}
