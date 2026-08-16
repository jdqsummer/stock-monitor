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


class TestAnalysisRunStatusAPI:
    @pytest.mark.asyncio
    async def test_run_status_requires_auth(self, client):
        resp = await client.get("/api/analysis/run/status", params={"job_id": "job_x"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_status_returns_progress(self, client):
        token = await _auth_token(client, email="ar3@example.com")
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]

        svc = analysis_api.analysis_job_service
        svc._jobs["job_run_x"] = {
            "job_id": "job_run_x", "user_id": user_id, "source": "analysis_page",
            "created_at": "2026-08-16T15:30:00",
            "codes": {"600519": STATUS_DONE, "000858": "pending"},
        }
        resp = await client.get(
            "/api/analysis/run/status", params={"job_id": "job_run_x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] == "job_run_x"
        assert data["total"] == 2
        assert data["done"] == 1

    @pytest.mark.asyncio
    async def test_run_status_denies_other_user(self, client):
        owner_token = await _auth_token(client, email="ar4@example.com")
        owner_me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
        owner_id = owner_me.json()["data"]["id"]
        svc = analysis_api.analysis_job_service
        svc._jobs["job_run_y"] = {
            "job_id": "job_run_y", "user_id": owner_id, "source": "analysis_page",
            "created_at": "2026-08-16T15:30:00",
            "codes": {"600519": STATUS_DONE},
        }
        other_token = await _auth_token(client, email="ar5@example.com")
        resp = await client.get(
            "/api/analysis/run/status", params={"job_id": "job_run_y"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404


class TestAnalysisRunActiveAPI:
    @pytest.mark.asyncio
    async def test_run_active_requires_auth(self, client):
        resp = await client.get("/api/analysis/run/active")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_run_active_scoped_to_analysis_page(self, client):
        """只返回 source=analysis_page 的进行中 job，不抢 manual/portfolio job"""
        token = await _auth_token(client, email="ar6@example.com")
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        user_id = me.json()["data"]["id"]
        svc = analysis_api.analysis_job_service
        svc._jobs["job_wl"] = {
            "job_id": "job_wl", "user_id": user_id, "source": "manual",
            "created_at": "2026-08-16T15:30:00", "codes": {"600519": "running"},
        }
        svc._jobs["job_page"] = {
            "job_id": "job_page", "user_id": user_id, "source": "analysis_page",
            "created_at": "2026-08-16T15:40:00", "codes": {"000858": "running"},
        }
        resp = await client.get(
            "/api/analysis/run/active", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["job_id"] == "job_page"

    @pytest.mark.asyncio
    async def test_run_active_404_when_none(self, client):
        token = await _auth_token(client, email="ar7@example.com")
        resp = await client.get(
            "/api/analysis/run/active", headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
