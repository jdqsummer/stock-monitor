import pytest
from sqlalchemy import select

from backend.models.stock import AnalysisSnapshot


async def _auth_token(client) -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": "analyze@example.com", "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": "analyze@example.com", "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "analyze@example.com", "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


class TestAnalysisSnapshot:
    @pytest.mark.asyncio
    async def test_analyze_requires_auth(self, client):
        resp = await client.post("/api/analysis/analyze", json={"code": "600519"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_analyze_persists_snapshot(self, client, mock_redis, db_session):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post("/api/analysis/analyze", json={"code": "600519"}, headers=headers)
        assert resp.status_code == 200

        snapshots = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
        assert len(snapshots) == 1
        assert snapshots[0].stock_code == "600519"
        assert snapshots[0].signal in {"green", "yellow", "red"}


def test_analyze_request_use_llm_defaults_true():
    from backend.api.analysis import AnalyzeRequest
    req = AnalyzeRequest(code="600519")
    assert req.use_llm is True


class TestSnapshotEngineMetadata:
    @pytest.mark.asyncio
    async def test_snapshot_detail_includes_engine_metadata(self, client, mock_redis, db_session):
        token = await _auth_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        me = await client.get("/api/auth/me", headers=headers)
        user_id = me.json()["data"]["id"]
        # 直接落一条带引擎元数据的快照，再经 /analysis/snapshot/{code} 读回
        from datetime import date
        from backend.agents.analysis_chain import AnalysisReport
        from backend.models.stock import StockSnapshot
        from backend.services.snapshot_svc import SnapshotService
        db_session.add(StockSnapshot(code="600519", name="贵州茅台", current_price=1560.0,
                                     total_market_cap=19500.0))
        await db_session.commit()
        await SnapshotService.save_snapshot(
            db_session, user_id, AnalysisReport(
                code="600519", name="贵州茅台", data_date=date.today().isoformat(),
                analysis_source="dsh-llm", analysis_model="deepseek-v4-flash",
                analysis_degraded=False,
            ),
        )
        resp = await client.get("/api/analysis/snapshot/600519", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["analysis_model"] == "deepseek-v4-flash"
        assert data["analysis_degraded"] is False
