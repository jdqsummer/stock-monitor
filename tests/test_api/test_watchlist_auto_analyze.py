import pytest

from backend.api import watchlist as watchlist_api


async def _auth_token(client) -> str:
    await client.post("/api/auth/register/send-code", json={
        "email": "wa@example.com", "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": "wa@example.com", "code": "000000", "password": "pass1234",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "wa@example.com", "password": "pass1234",
    })
    return resp.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_add_watchlist_triggers_analysis(client, monkeypatch):
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: True)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "600519", "stock_name": "贵州茅台",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls, "LLM 可用时应触发分析"
    assert calls[0][1] == ["600519"]
    assert calls[0][2] == "watchlist_add"


@pytest.mark.asyncio
async def test_add_watchlist_skips_when_llm_mock(client, monkeypatch):
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: False)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "600519", "stock_name": "贵州茅台",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls == [], "LLM mock 时不触发分析"
