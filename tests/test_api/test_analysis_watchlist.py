import pytest
from datetime import date

from backend.models.stock import AnalysisSnapshot, StockSnapshot
from backend.services.analysis_job_svc import STATUS_DONE


async def _auth_token(client, email: str = "wl@example.com") -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": email, "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": email, "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": email, "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


class TestWatchlistAnalyzeAPI:
    @pytest.mark.asyncio
    async def test_analyze_requires_auth(self, client):
        resp = await client.post("/api/analysis/watchlist/analyze", json={"codes": ["600519"]})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_watchlist_returns_job_id(self, client, monkeypatch):
        from backend.api import analysis as analysis_api

        calls = []
        def fake_submit(user_id, codes, source):
            calls.append((user_id, codes, source))
            return "job_abc"
        monkeypatch.setattr(analysis_api.analysis_job_service, "submit", fake_submit)

        token = await _auth_token(client)
        resp = await client.post(
            "/api/analysis/watchlist/analyze", json={"codes": ["600519", "000858"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["job_id"] == "job_abc"
        assert calls and calls[0][1] == ["600519", "000858"]
        assert calls[0][2] == "manual"

    @pytest.mark.asyncio
    async def test_status_returns_progress(self, client):
        from backend.api import analysis as analysis_api

        token = await _auth_token(client)
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]

        svc = analysis_api.analysis_job_service
        svc._jobs["job_x"] = {
            "job_id": "job_x", "user_id": user_id, "source": "manual",
            "created_at": "2026-08-12T15:30:00",
            "codes": {"600519": STATUS_DONE, "000858": "pending"},
        }
        resp = await client.get(
            "/api/analysis/watchlist/status", params={"job_id": "job_x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert data["done"] == 1

    @pytest.mark.asyncio
    async def test_status_denies_other_user(self, client):
        """job 归属校验：非属主用户查询同一 job 返回 404"""
        from backend.api import analysis as analysis_api

        owner_token = await _auth_token(client)
        owner_me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
        owner_id = owner_me.json()["data"]["id"]

        svc = analysis_api.analysis_job_service
        svc._jobs["job_y"] = {
            "job_id": "job_y", "user_id": owner_id, "source": "manual",
            "created_at": "2026-08-12T15:30:00",
            "codes": {"600519": STATUS_DONE, "000858": "pending"},
        }

        other_token = await _auth_token(client, email="wl2@example.com")
        resp = await client.get(
            "/api/analysis/watchlist/status", params={"job_id": "job_y"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404


class TestSnapshotAPI:
    @pytest.mark.asyncio
    async def test_snapshot_404_when_not_analyzed(self, client, db_session):
        token = await _auth_token(client)
        resp = await client.get(
            "/api/analysis/snapshot/600519", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_snapshot_returns_qualitative(self, client, db_session, mock_redis):
        token = await _auth_token(client)
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]

        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0))
        db_session.add(AnalysisSnapshot(
            user_id=user_id, stock_code="600519",
            annual_profit_low=688, annual_profit_high=842, profit_method="H1×2",
            pe_low=20, pe_high=35,
            swing_market_cap_low=13760, swing_market_cap_high=29470,
            swing_price_low=1147, swing_price_high=2456,
            current_market_cap=19500, current_price=1560,
            distance_pct=-38.9, signal="green", signal_label="击球区",
            rating="🟢", data_date=date(2026, 8, 12),
            industry_category="白酒", moat_assessment="品牌护城河",
            risk_factors='["宏观风险"]', recommendation="可分批建仓",
            analysis_source="scheduled",
        ))
        await db_session.commit()

        resp = await client.get(
            "/api/analysis/snapshot/600519", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "贵州茅台"
        assert data["signal"] == "green"
        assert data["signal_label"] == "击球区"
        assert data["moat_assessment"] == "品牌护城河"
        assert data["risk_factors"] == ["宏观风险"]
        assert data["recommendation"] == "可分批建仓"
        assert data["analysis_source"] == "scheduled"
