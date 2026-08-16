import pytest

from backend.api import analysis as analysis_api
from backend.agents.analysis_chain import AnalysisReport
from backend.services.analysis_job_svc import STATUS_DONE


async def _auth_token(client, email: str = "ar@example.com") -> str:
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


class TestAnalysisRunAPI:
    @pytest.mark.asyncio
    async def test_run_requires_auth(self, client):
        resp = await client.post("/api/analysis/run", json={"code": "600519"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_llm_available_submits_job(self, client, monkeypatch):
        """LLM 可用 → 提交 source=analysis_page 的异步 job，返回 mode=async"""
        calls = []
        def fake_submit(user_id, codes, source, model=""):
            calls.append((user_id, codes, source, model))
            return "job_run"
        monkeypatch.setattr(analysis_api.analysis_job_service, "submit", fake_submit)
        monkeypatch.setattr(analysis_api, "is_llm_available", lambda: True)

        token = await _auth_token(client)
        resp = await client.post(
            "/api/analysis/run",
            json={"code": "600519", "name": "贵州茅台", "model": "deepseek-v4-pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] == "job_run"
        assert data["mode"] == "async"
        assert calls and calls[0][1] == ["600519"]
        assert calls[0][2] == "analysis_page"
        assert calls[0][3] == "deepseek-v4-pro"

    @pytest.mark.asyncio
    async def test_run_llm_mock_degrades_to_rule_based(self, client, monkeypatch):
        """LLM 不可用 → 同步纯规则链（llm_provider=None）+ 落库 source=rule-based，返回 mode=sync_degraded"""
        calls = []
        def fake_submit(user_id, codes, source, model=""):
            calls.append((user_id, codes, source, model))
            return "job_run"
        monkeypatch.setattr(analysis_api.analysis_job_service, "submit", fake_submit)
        monkeypatch.setattr(analysis_api, "is_llm_available", lambda: False)

        saved = {}
        class FakeChain:
            def __init__(self, llm_provider=None):
                saved["llm_provider"] = llm_provider
            async def analyze(self, **kwargs):
                saved["analyze_kwargs"] = kwargs
                return AnalysisReport(code=kwargs["code"], name=kwargs.get("stock_name", ""))
        monkeypatch.setattr(analysis_api, "AnalysisChain", FakeChain)

        async def fake_save(db, user_id, report, source="manual"):
            saved["source"] = source
            saved["user_id"] = user_id
        monkeypatch.setattr(analysis_api.SnapshotService, "save_snapshot", fake_save)

        token = await _auth_token(client, email="ar2@example.com")
        resp = await client.post(
            "/api/analysis/run",
            json={"code": "600519", "name": "贵州茅台"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] is None
        assert data["mode"] == "sync_degraded"
        assert calls == []
        assert saved["llm_provider"] is None
        assert saved["source"] == "rule-based"
        assert saved["analyze_kwargs"]["code"] == "600519"
