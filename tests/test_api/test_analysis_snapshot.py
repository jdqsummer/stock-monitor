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
