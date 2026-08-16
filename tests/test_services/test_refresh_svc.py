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


@pytest.mark.asyncio
async def test_refresh_financials_writes_multiple_periods(db_session):
    from backend.models.stock import FinancialRecord

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="茅台"))
    await db_session.commit()

    count = await RefreshService.refresh_financials(db_session)
    assert count == 8

    rows = (await db_session.execute(
        select(FinancialRecord).where(FinancialRecord.code == "600519")
    )).scalars().all()
    periods = {r.report_period for r in rows}
    assert len(rows) == 8
    assert "2026H1" in periods and "2024FY" in periods


@pytest.mark.asyncio
async def test_collect_quote_refresh_users_filters_no_watchlist(db_session):
    """无自选股的用户不进刷新；有自选股返回 (user_id, 间隔)"""
    from backend.models.user import User
    from backend.models.stock import WatchlistItem
    from backend.services.refresh_svc import collect_quote_refresh_users

    db_session.add(User(id="u_empty", email="e1@x.com", password_hash="x"))
    db_session.add(User(id="u_full", email="e2@x.com", password_hash="x",
                        config={"data_refresh_interval_minutes": 15}))
    db_session.add(WatchlistItem(user_id="u_full", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    rows = await collect_quote_refresh_users(db_session)
    ids = {u for u, _ in rows}
    assert "u_empty" not in ids
    assert dict(rows)["u_full"] == 15


@pytest.mark.asyncio
async def test_collect_quote_refresh_users_returns_raw_interval(db_session):
    """脏数据（非数字/None）不抛异常，返回原始值交由 sync_quote_refresh_jobs 统一校验"""
    from backend.models.user import User
    from backend.services.refresh_svc import collect_quote_refresh_users

    db_session.add(User(id="u_bad", email="bad@x.com", password_hash="x",
                        config={"data_refresh_interval_minutes": "abc"}))
    db_session.add(User(id="u_none", email="none@x.com", password_hash="x",
                        config={"data_refresh_interval_minutes": None}))
    db_session.add(WatchlistItem(user_id="u_bad", stock_code="600519", stock_name="贵州茅台"))
    db_session.add(WatchlistItem(user_id="u_none", stock_code="000333", stock_name="美的"))
    await db_session.commit()

    rows = await collect_quote_refresh_users(db_session)
    d = dict(rows)
    assert d["u_bad"] == "abc"
    assert d["u_none"] is None


@pytest.mark.asyncio
async def test_collect_auto_analysis_users_uses_concurrency_default(db_session):
    """collect 返回 (user_id, time)；run_user_auto_analysis 读配置并发"""
    from backend.models.user import User
    from backend.models.stock import WatchlistItem
    from backend.services.refresh_svc import collect_auto_analysis_users

    db_session.add(User(id="u_a", email="a@x.com", password_hash="x",
                        config={"analysis_auto_enabled": True,
                                "analysis_schedule_afternoon": "15:00",
                                "analysis_concurrency": 5}))
    db_session.add(WatchlistItem(user_id="u_a", stock_code="600519", stock_name="贵州茅台"))
    await db_session.commit()

    rows = await collect_auto_analysis_users(db_session)
    assert ("u_a", "15:00") in rows


@pytest.mark.asyncio
async def test_run_user_auto_analysis_submits_concurrency(test_session_factory, monkeypatch):
    """scheduled 提交带 concurrency + 混合 mode；用 monkeypatch 桩掉 submit 记录参数"""
    from backend.services import refresh_svc as mod

    calls = {}
    def fake_submit(user_id, codes, source, concurrency=None, **kw):
        calls.update(user_id=user_id, concurrency=concurrency,
                     codes=list(codes), modes=kw.get("modes"))
    monkeypatch.setattr(mod.analysis_job_service, "submit", fake_submit)

    from backend.models.user import User
    from backend.models.stock import WatchlistItem
    from backend.models.portfolio import Position
    async with test_session_factory() as s:
        s.add(User(id="u_c", email="c@x.com", password_hash="x",
                   config={"analysis_concurrency": 7}))
        s.add(WatchlistItem(user_id="u_c", stock_code="600519", stock_name="贵州茅台"))
        s.add(Position(user_id="u_c", stock_code="600519", stock_name="贵州茅台"))
        await s.commit()

    await mod.run_user_auto_analysis("u_c", session_factory=test_session_factory)
    assert calls["user_id"] == "u_c" and calls["concurrency"] == 7
    assert calls["codes"] == ["600519"]
    assert calls["modes"] == {"600519": "position"}


@pytest.mark.asyncio
async def test_auto_analysis_mixed_mode(db_session):
    """自动分析：持仓股 position 模式 + 纯自选股 watchlist 模式，合并去重"""
    from backend.models.user import User
    from backend.models.portfolio import Position
    from backend.services.refresh_svc import collect_auto_analysis_codes

    user = User(email="mix@example.com", password_hash="x",
                config={"analysis_auto_enabled": True})
    db_session.add(user)
    await db_session.commit()
    # 持仓（也属自选）+ 纯自选
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id=user.id, stock_code="600519", stock_name="茅台"))
    db_session.add(WatchlistItem(user_id=user.id, stock_code="000858", stock_name="五粮液"))
    await db_session.commit()

    watchlist, positions = await collect_auto_analysis_codes(db_session, user.id)
    assert "600519" in positions and "600519" in watchlist
    assert "000858" in watchlist and "000858" not in positions
