# stock-monitor/tests/test_api/test_watchlist.py
import pytest
from unittest.mock import AsyncMock, patch

from backend.data.providers.base import ProviderError
from backend.schemas.stock import StockQuote


async def _auth_token(client) -> str:
    """注册并登录，返回 access_token"""
    resp = await client.post("/api/auth/register/send-code", json={
        "email": "watch@example.com",
        "purpose": "register",
    })
    assert resp.status_code == 200
    resp = await client.post("/api/auth/register", json={
        "email": "watch@example.com",
        "code": "000000",
        "password": "pass1234",
    })
    assert resp.status_code == 200
    resp = await client.post("/api/auth/login", json={
        "email": "watch@example.com",
        "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


def _mock_quote():
    return StockQuote(
        code="600519", name="贵州茅台", current_price=1560.0, change_pct=1.2,
        total_market_cap=19500.0, pe_dynamic=25.3, total_shares=12.6,
    )


class TestWatchlistAPI:
    @pytest.mark.asyncio
    async def test_requires_auth(self, client):
        """未认证 → 401"""
        resp = await client.get("/api/watchlist")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_add_and_list(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "添加成功"

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) == 1
        assert items[0]["stock_code"] == "600519"
        assert items[0]["stock_name"] == "贵州茅台"

    @pytest.mark.asyncio
    async def test_add_duplicate_409(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        resp = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        assert resp.status_code == 409
        assert resp.json()["detail"] == "该股票已在自选股中: 600519 贵州茅台"

    @pytest.mark.asyncio
    async def test_remove(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        added = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        item_id = added.json()["data"]["id"]

        resp = await client.delete(f"/api/watchlist/{item_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["message"] == "已删除"

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.json()["data"] == []

    @pytest.mark.asyncio
    async def test_remove_not_found(self, client):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.delete("/api/watchlist/not-exist", headers=headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_industry(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        added = await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)
        item_id = added.json()["data"]["id"]

        resp = await client.patch(f"/api/watchlist/{item_id}", json={
            "industry": "白酒",
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["industry"] == "白酒"

    @pytest.mark.asyncio
    async def test_auto_classify(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        resp = await client.post("/api/watchlist/auto-classify", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] == 1

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.json()["data"][0]["industry"] == "白酒"

    @pytest.mark.asyncio
    async def test_search(self, client, mock_redis):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        with patch(
            "backend.api.watchlist._client.search_stock",
            AsyncMock(return_value=[_mock_quote()]),
        ), patch(
            "backend.api.watchlist._client.fetch_quote",
            AsyncMock(return_value=_mock_quote()),
        ):
            resp = await client.get(
                "/api/watchlist/search", params={"keyword": "600519"}, headers=headers,
            )
        assert resp.status_code == 200
        results = resp.json()["data"]
        assert len(results) == 1
        assert results[0]["code"] == "600519"
        assert results[0]["name"] == "贵州茅台"

    @pytest.mark.asyncio
    async def test_search_enriched_with_quote(self, client, mock_redis):
        """搜索返回的占位零值行情，应被实时行情富化（下拉/详情面板展示真实数据）"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        meta = StockQuote(
            code="688825", name="长鑫科技",
            current_price=0.0, total_market_cap=0.0,
        )
        quote = StockQuote(
            code="688825", name="长鑫科技", current_price=50.82, change_pct=0.83,
            change_amount=0.42, total_market_cap=33988.87, turnover_rate=0.56,
            pe_dynamic=120.55, total_shares=668.81,
        )
        with patch(
            "backend.api.watchlist._client.search_stock",
            AsyncMock(return_value=[meta]),
        ), patch(
            "backend.api.watchlist._client.fetch_quote",
            AsyncMock(return_value=quote),
        ):
            resp = await client.get(
                "/api/watchlist/search", params={"keyword": "长鑫科技"}, headers=headers,
            )
        assert resp.status_code == 200
        result = resp.json()["data"][0]
        assert result["code"] == "688825"
        assert result["name"] == "长鑫科技"
        assert result["current_price"] == 50.82
        assert result["change_pct"] == 0.83
        assert result["change_amount"] == 0.42
        assert result["total_market_cap"] == 33988.87
        assert result["turnover_rate"] == 0.56
        assert result["pe_dynamic"] == 120.55
        assert result["total_shares"] == 668.81

    @pytest.mark.asyncio
    async def test_search_quote_failure_keeps_meta(self, client, mock_redis):
        """某只股票行情拉取失败时，保留搜索返回的 code/name 元数据，不中断整批"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        meta = StockQuote(
            code="688825", name="长鑫科技",
            current_price=0.0, total_market_cap=0.0,
        )
        with patch(
            "backend.api.watchlist._client.search_stock",
            AsyncMock(return_value=[meta]),
        ), patch(
            "backend.api.watchlist._client.fetch_quote",
            AsyncMock(side_effect=ProviderError("行情失败")),
        ):
            resp = await client.get(
                "/api/watchlist/search", params={"keyword": "长鑫科技"}, headers=headers,
            )
        assert resp.status_code == 200
        result = resp.json()["data"][0]
        assert result["code"] == "688825"
        assert result["name"] == "长鑫科技"
