import pytest
from datetime import date

from backend.models.stock import AnalysisSnapshot, StockSnapshot, WatchlistItem
from backend.models.portfolio import Position


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
