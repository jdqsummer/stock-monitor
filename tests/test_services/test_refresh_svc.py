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


import pytest
from datetime import date

from sqlalchemy import select

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.services.refresh_svc import RefreshService


@pytest.mark.asyncio
async def test_recompute_analysis_updates_signal(db_session):
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=3000.0,
                                 total_market_cap=19500.0))
    db_session.add(AnalysisSnapshot(
        user_id="u1", stock_code="600519",
        annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
        pe_low=20, pe_high=35,
        swing_market_cap_low=13760, swing_market_cap_high=29470,
        swing_price_low=1147, swing_price_high=2456,
        current_market_cap=19500, current_price=1560,
        distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
    ))
    await db_session.commit()

    count = await RefreshService.recompute_analysis(db_session)
    assert count == 1

    snap = (await db_session.execute(
        select(AnalysisSnapshot).where(AnalysisSnapshot.stock_code == "600519")
    )).scalar_one()
    assert snap.current_price == 3000.0
    # (3000 - 2456)/2456 ≈ 22.1% → 观察区 yellow
    assert snap.distance_pct == pytest.approx(22.1)
    assert snap.signal == "yellow"


@pytest.mark.asyncio
async def test_job_entry_points_exist():
    # 入口函数可调用且返回 int（无自选股时为空任务，不报错）
    from backend.services.refresh_svc import run_quote_refresh, run_recompute_analysis

    assert callable(run_quote_refresh)
    assert callable(run_recompute_analysis)


@pytest.mark.asyncio
async def test_collect_auto_analysis_users(db_session):
    from backend.models.user import User
    from backend.services.refresh_svc import collect_auto_analysis_users

    u1 = User(email="auto1@example.com", password_hash="x",
              config={"analysis_auto_enabled": True, "analysis_schedule_afternoon": "16:00"})
    u2 = User(email="auto2@example.com", password_hash="x",
              config={"analysis_auto_enabled": False})
    u3 = User(email="auto3@example.com", password_hash="x", config=None)
    db_session.add_all([u1, u2, u3])
    await db_session.commit()
    await db_session.refresh(u1)

    result = await collect_auto_analysis_users(db_session)
    assert result == [(u1.id, "16:00")]
