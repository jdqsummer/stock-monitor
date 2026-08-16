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


@pytest.mark.asyncio
async def test_add_watchlist_skip_analysis_true_skips_submit(client, monkeypatch):
    """skip_analysis=true（Analysis 页刚分析完同一只股）→ 不提交自动分析 job"""
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: True)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "600519", "stock_name": "贵州茅台", "skip_analysis": True,
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls == [], "skip_analysis=true 时不提交自动分析"


@pytest.mark.asyncio
async def test_add_watchlist_skip_analysis_default_false_still_triggers(client, monkeypatch):
    """默认 skip_analysis=false：LLM 可用仍触发分析（回归现有行为）"""
    calls = []
    def fake_submit(user_id, codes, source):
        calls.append((user_id, codes, source))
        return "job_x"
    monkeypatch.setattr(watchlist_api.analysis_job_service, "submit", fake_submit)
    monkeypatch.setattr(watchlist_api, "is_llm_available", lambda: True)

    token = await _auth_token(client)
    resp = await client.post("/api/watchlist", json={
        "stock_code": "000858", "stock_name": "五粮液",
    }, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert calls and calls[0][2] == "watchlist_add"
