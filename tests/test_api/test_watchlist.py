# stock-monitor/tests/test_api/test_watchlist.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from backend.data.providers.base import ProviderError
from backend.models.stock import AnalysisSnapshot, WatchlistItem
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


async def _auth_user(client) -> tuple[str, str]:
    """注册并登录，返回 (access_token, user_id)"""
    token = await _auth_token(client)
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["data"]["id"]


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
        # 添加即提取智能分类（内置映射命中，无需数据源）
        assert resp.json()["data"]["industry"] == "白酒"

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["data"]
        assert len(items) == 1
        assert items[0]["stock_code"] == "600519"
        assert items[0]["stock_name"] == "贵州茅台"
        assert items[0]["industry"] == "白酒"

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
    async def test_list_enriched_with_quote(self, client, mock_redis):
        """列表应并行富化实时行情：现价/总市值/动态PE"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        with patch(
            "backend.api.watchlist._client.fetch_quote",
            AsyncMock(return_value=_mock_quote()),
        ):
            resp = await client.get("/api/watchlist", headers=headers)
        assert resp.status_code == 200
        item = resp.json()["data"][0]
        assert item["current_price"] == 1560.0
        assert item["total_market_cap"] == 19500.0
        assert item["pe_dynamic"] == 25.3
        assert "added_at" not in item
        # 无分析快照 → 派生字段降级为 None
        assert item["swing_market_cap"] is None
        assert item["swing_price"] is None
        assert item["distance_pct"] is None
        assert item["signal"] is None
        assert item["analysis_source"] is None

    @pytest.mark.asyncio
    async def test_list_enriched_with_analysis(self, client, mock_redis, db_session):
        """列表应返回分析快照派生字段：击球区市值/股价、距击球区、信号"""
        token, user_id = await _auth_user(client)
        headers = {"Authorization": f"Bearer {token}"}
        db_session.add(WatchlistItem(user_id=user_id, stock_code="600519", stock_name="贵州茅台", industry="白酒"))
        db_session.add(AnalysisSnapshot(
            user_id=user_id, stock_code="600519",
            annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
            pe_low=20, pe_high=35,
            swing_market_cap_low=13760, swing_market_cap_high=29470,
            swing_price_low=1147, swing_price_high=2456,
            current_market_cap=19500, current_price=1560,
            distance_pct=-38.9, signal="green", data_date=date(2026, 8, 11),
            analysis_source="dsh-llm",
        ))
        await db_session.commit()

        with patch("backend.api.watchlist._client.fetch_quote", AsyncMock(return_value=_mock_quote())):
            resp = await client.get("/api/watchlist", headers=headers)
        assert resp.status_code == 200
        item = resp.json()["data"][0]
        assert item["swing_market_cap"] == "13760-29470亿"
        assert item["swing_price"] == "1147-2456元"
        # 实时价 1560 vs 击球区上沿 2456 → 距击球区 -36.5%，信号绿
        assert item["distance_pct"] == -36.5
        assert item["signal"] == "green"
        assert item["analysis_source"] == "dsh-llm"

    @pytest.mark.asyncio
    async def test_list_quote_failure_degrades(self, client, mock_redis):
        """行情拉取失败时列表仍返回，现价/市值/PE 降级为占位值，不中断"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        with patch(
            "backend.api.watchlist._client.fetch_quote",
            AsyncMock(side_effect=ProviderError("行情失败")),
        ):
            resp = await client.get("/api/watchlist", headers=headers)
        assert resp.status_code == 200
        item = resp.json()["data"][0]
        assert item["stock_code"] == "600519"
        assert item["current_price"] == 0.0
        assert item["total_market_cap"] == 0.0
        assert item["pe_dynamic"] is None

    @pytest.mark.asyncio
    async def test_auto_classify_idempotent(self, client, mock_redis):
        """添加已提取分类，一键分类再跑无变化：更新数为 0"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/watchlist", json={
            "stock_code": "600519", "stock_name": "贵州茅台",
        }, headers=headers)

        resp = await client.post("/api/watchlist/auto-classify", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] == 0

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.json()["data"][0]["industry"] == "白酒"

    @pytest.mark.asyncio
    async def test_add_classifies_via_provider(self, client, mock_redis):
        """内置映射未收录的股票：添加时经 provider 链补全行业"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        with patch(
            "backend.api.watchlist._client.fetch_industry",
            AsyncMock(return_value="电气设备-电源设备-储能设备"),
        ):
            resp = await client.post("/api/watchlist", json={
                "stock_code": "300750", "stock_name": "宁德时代",
            }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["industry"] == "电气设备-电源设备-储能设备"

    @pytest.mark.asyncio
    async def test_add_classify_failure_degrades(self, client, mock_redis):
        """添加时行业提取失败：添加仍成功，industry 为 None，不阻断"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        with patch(
            "backend.api.watchlist._client.fetch_industry",
            AsyncMock(side_effect=ProviderError("无行业数据")),
        ):
            resp = await client.post("/api/watchlist", json={
                "stock_code": "300750", "stock_name": "宁德时代",
            }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["industry"] is None

    @pytest.mark.asyncio
    async def test_auto_classify_fills_after_provider_recovers(self, client, mock_redis):
        """添加时数据源不可用（industry 为 None），后续一键分类补全"""
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        with patch(
            "backend.api.watchlist._client.fetch_industry",
            AsyncMock(side_effect=ProviderError("无行业数据")),
        ):
            await client.post("/api/watchlist", json={
                "stock_code": "300750", "stock_name": "宁德时代",
            }, headers=headers)

        with patch(
            "backend.api.watchlist._client.fetch_industry",
            AsyncMock(return_value="电气设备-电源设备-储能设备"),
        ):
            resp = await client.post("/api/watchlist/auto-classify", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] == 1

        resp = await client.get("/api/watchlist", headers=headers)
        assert resp.json()["data"][0]["industry"] == "电气设备-电源设备-储能设备"

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
