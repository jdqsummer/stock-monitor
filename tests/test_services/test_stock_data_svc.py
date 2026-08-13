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
