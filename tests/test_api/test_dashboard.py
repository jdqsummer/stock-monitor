import pytest
import pytest_asyncio
from datetime import date, datetime

from backend.models.stock import AnalysisSnapshot, StockSnapshot, WatchlistItem
from backend.models.portfolio import Position


def user_headers(user):
    """直接签发当前用户 JWT（镜像 test_portfolio 的 auth 模式，免注册流程）"""
    from backend.services.auth_svc import AuthService
    token = AuthService.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user(db_session):
    """在测试库直接落一个已认证用户，供 get_current_user 按 id 命中"""
    from backend.models.user import User
    from backend.services.auth_svc import AuthService
    u = User(email="dash-enriched@example.com",
             password_hash=AuthService.hash_password("pass1234"),
             email_verified=True)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _auth_user(client) -> tuple[str, str]:
    """注册并登录，返回 (access_token, user_id)"""
    await client.post("/api/auth/register/send-code", json={
        "email": "dash@example.com", "purpose": "register",
    })
    resp = await client.post("/api/auth/register", json={
        "email": "dash@example.com", "code": "000000", "password": "pass1234",
    })
    assert resp.status_code == 200
    resp = await client.post("/api/auth/login", json={
        "email": "dash@example.com", "password": "pass1234",
    })
    token = resp.json()["data"]["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["data"]["id"]


class TestDashboardAPI:
    @pytest.mark.asyncio
    async def test_watchlist_status_requires_auth(self, client):
        resp = await client.get("/api/dashboard/watchlist-status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_watchlist_status_returns_board_rows(
        self, client, mock_redis, db_session,
    ):
        token, user_id = await _auth_user(client)
        headers = {"Authorization": f"Bearer {token}"}

        # 直接构造 watchlist + B 快照 + A 行情
        db_session.add(WatchlistItem(user_id=user_id, stock_code="600519", stock_name="贵州茅台", industry="白酒"))
        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0))
        db_session.add(AnalysisSnapshot(
            user_id=user_id, stock_code="600519",
            annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
            pe_low=20, pe_high=35,
            swing_market_cap_low=13760, swing_market_cap_high=29470,
            swing_price_low=1147, swing_price_high=2456,
            current_market_cap=19500, current_price=1560,
            distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
        ))
        await db_session.commit()

        resp = await client.get("/api/dashboard/watchlist-status", headers=headers)
        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert len(rows) == 1
        assert rows[0]["code"] == "600519"
        assert rows[0]["signal"] == "green"
        assert rows[0]["annual_profit"] == "688-842亿"

    @pytest.mark.asyncio
    async def test_overview_and_positions(
        self, client, mock_redis, db_session,
    ):
        token, user_id = await _auth_user(client)
        headers = {"Authorization": f"Bearer {token}"}
        db_session.add(Position(
            user_id=user_id, stock_code="600519", stock_name="贵州茅台",
            shares=100, cost_price=1400.0,
        ))
        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0, pe_dynamic=25.3))
        await db_session.commit()

        resp = await client.get("/api/dashboard/overview", headers=headers)
        assert resp.status_code == 200
        overview = resp.json()["data"]
        assert overview["position_count"] == 1
        assert overview["total_market_value"] == 156000.0

        resp = await client.get("/api/dashboard/positions", headers=headers)
        assert resp.status_code == 200
        positions = resp.json()["data"]
        assert len(positions) == 1
        assert positions[0]["current_price"] == 1560.0
        assert positions[0]["pe_dynamic"] == 25.3


@pytest.mark.asyncio
async def test_dashboard_overview_daily_pl_computed(client, db_session, user):
    """overview daily_pl 不再硬编码 0：用行情 change_pct 反推昨收计算"""
    from backend.models.portfolio import Position
    from backend.models.stock import StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=100, cost_price=90.0, purchased_at=None))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    await db_session.commit()
    res = await client.get("/api/dashboard/overview", headers=user_headers(user))
    data = res.json()["data"]
    # 昨收=100，当日盈亏=(105-100)*100=500
    assert data["daily_pl"] == pytest.approx(500.0, abs=0.1)


@pytest.mark.asyncio
async def test_dashboard_positions_sell_enriched(client, db_session, user):
    from backend.models.portfolio import Position
    from backend.models.stock import AnalysisSnapshot, StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=100, cost_price=80.0, purchased_at=datetime(2026, 8, 1)))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    db_session.add(AnalysisSnapshot(user_id=user.id, stock_code="600519",
                                    sell_price_low=100.0, sell_price_high=120.0,
                                    sell_distance_pct=5.0, sell_signal="red", sell_action="sell"))
    await db_session.commit()
    res = await client.get("/api/dashboard/positions", headers=user_headers(user))
    row = res.json()["data"][0]
    assert row["holding_days"] is not None
    assert row["sell_distance_pct"] == 5.0
    assert row["sell_signal"] == "red"


@pytest.mark.asyncio
async def test_dashboard_positions_sell_fallback(client, db_session, user):
    """快照仅有 sell_price_low、无 sell_distance/signal → calc_sell_signal 兜底重算"""
    from backend.models.portfolio import Position
    from backend.models.stock import AnalysisSnapshot, StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=100, cost_price=80.0, purchased_at=datetime(2026, 8, 1)))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    db_session.add(AnalysisSnapshot(user_id=user.id, stock_code="600519",
                                    annual_profit_low=50.0,
                                    sell_price_low=100.0, sell_price_high=120.0))
    await db_session.commit()
    res = await client.get("/api/dashboard/positions", headers=user_headers(user))
    row = res.json()["data"][0]
    # 兜底重算：现价 105 → 距卖出区 = (105-100)/100 = 5.0 / red
    assert row["sell_price_low"] == 100.0
    assert row["sell_distance_pct"] == 5.0
    assert row["sell_signal"] == "red"


@pytest.mark.asyncio
async def test_dashboard_overview_skips_empty_shares(client, db_session, user):
    """overview 空 shares 行不参与聚合（无 TypeError），position_count 仍计入"""
    from backend.models.portfolio import Position
    from backend.models.stock import StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=None, cost_price=None, purchased_at=None))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    await db_session.commit()
    res = await client.get("/api/dashboard/overview", headers=user_headers(user))
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["position_count"] == 1
    assert data["total_market_value"] == 0.0
    assert data["daily_pl"] == 0.0


@pytest.mark.asyncio
async def test_dashboard_positions_skips_empty_shares(client, db_session, user):
    """positions 空 shares/cost_price 行正常序列化（null），不返回 500"""
    from backend.models.portfolio import Position
    from backend.models.stock import StockSnapshot
    db_session.add(Position(user_id=user.id, stock_code="600519", stock_name="贵州茅台",
                            shares=None, cost_price=None, purchased_at=None))
    db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=105.0,
                                 change_pct=5.0, total_market_cap=1000.0))
    await db_session.commit()
    res = await client.get("/api/dashboard/positions", headers=user_headers(user))
    assert res.status_code == 200
    row = res.json()["data"][0]
    assert row["shares"] is None
    assert row["cost_price"] is None
