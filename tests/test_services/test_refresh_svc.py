import pytest
from sqlalchemy import select

from backend.models.stock import StockSnapshot, WatchlistItem
from backend.services.refresh_svc import RefreshService


@pytest.mark.asyncio
async def test_collect_watchlist_codes_dedup(db_session):
    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id="u2", stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id="u1", stock_code="000333", stock_name="美的"))
    await db_session.commit()
    codes = await RefreshService.collect_watchlist_codes(db_session)
    assert sorted(codes) == ["000333", "600519"]


@pytest.mark.asyncio
async def test_refresh_quotes_writes_a_table(db_session):
    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    await db_session.commit()
    count = await RefreshService.refresh_quotes(db_session)
    assert count == 1
    row = (await db_session.execute(
        select(StockSnapshot).where(StockSnapshot.code == "600519")
    )).scalar_one()
    # mock quote：价格 50.0、市值 800.0
    assert row.current_price == 50.0
    assert row.total_market_cap == 800.0


@pytest.mark.asyncio
async def test_refresh_quotes_keeps_old_on_failure(db_session, monkeypatch):
    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    await db_session.commit()
    await RefreshService.refresh_quotes(db_session)  # 先写入一次
    row_before = (await db_session.execute(
        select(StockSnapshot).where(StockSnapshot.code == "600519")
    )).scalar_one()

    async def boom(self, code):
        raise RuntimeError("third-party down")

    monkeypatch.setattr(
        "backend.services.refresh_svc.WestockClient.fetch_quote", boom,
    )
    count = await RefreshService.refresh_quotes(db_session)
    assert count == 0
    row_after = (await db_session.execute(
        select(StockSnapshot).where(StockSnapshot.code == "600519")
    )).scalar_one()
    assert row_after.current_price == row_before.current_price
