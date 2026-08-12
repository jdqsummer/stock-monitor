# stock-monitor/tests/test_api/test_config.py
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.models.user import User


async def _register_and_login(client: AsyncClient, email: str) -> str:
    """Helper: 注册并登录，返回 token"""
    await client.post("/api/auth/register/send-code", json={
        "email": email,
        "purpose": "register",
    })
    await client.post("/api/auth/register", json={
        "email": email,
        "code": "000000",
        "password": "testpass123",
    })
    resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": "testpass123",
    })
    return resp.json()["data"]["access_token"]


class TestConfig:
    @pytest.mark.asyncio
    async def test_get_default_config(self, client):
        token = await _register_and_login(client, "cfg_default@example.com")
        resp = await client.get("/api/config", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["llm_model"] == "deepseek-chat"
        assert data["data"]["llm_temperature"] == 0.3
        assert data["data"]["data_refresh_interval_minutes"] == 30

    @pytest.mark.asyncio
    async def test_update_config(self, client):
        token = await _register_and_login(client, "cfg_update@example.com")
        new_config = {
            "llm_model": "qwen-max",
            "llm_temperature": 0.5,
            "llm_max_tokens": 8192,
            "data_refresh_interval_minutes": 15,
            "analysis_schedule_morning": "08:00",
            "analysis_schedule_afternoon": "16:00",
            "westock_api_key": None,
            "investment_style": "value",
            "risk_tolerance": "conservative",
            "notification_enabled": True,
        }
        resp = await client.put("/api/config", json=new_config, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["llm_model"] == "qwen-max"
        assert data["data"]["risk_tolerance"] == "conservative"
        assert data["data"]["notification_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_config_persists_analysis_auto_enabled(self, client, db_session):
        """分析开关应持久化：PUT → GET 回显 → 库中 user.config JSON 均可见"""
        email = "cfg_auto_analysis@example.com"
        token = await _register_and_login(client, email)
        new_config = {
            "llm_model": "deepseek-chat",
            "llm_temperature": 0.3,
            "llm_max_tokens": 4096,
            "data_refresh_interval_minutes": 30,
            "analysis_schedule_morning": "09:30",
            "analysis_schedule_afternoon": "16:00",
            "westock_api_key": None,
            "investment_style": "value",
            "risk_tolerance": "moderate",
            "notification_enabled": True,
            "analysis_auto_enabled": True,
        }
        put_resp = await client.put("/api/config", json=new_config, headers={"Authorization": f"Bearer {token}"})
        assert put_resp.status_code == 200
        assert put_resp.json()["data"]["analysis_auto_enabled"] is True

        get_resp = await client.get("/api/config", headers={"Authorization": f"Bearer {token}"})
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["analysis_auto_enabled"] is True

        result = await db_session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        assert user.config["analysis_auto_enabled"] is True

    @pytest.mark.asyncio
    async def test_get_llm_models(self, client):
        resp = await client.get("/api/config/llm-models")
        assert resp.status_code == 200
        data = resp.json()
        models = data["data"]
        assert len(models) >= 4
        providers = {m["provider"] for m in models}
        assert "deepseek" in providers
        assert "qwen" in providers

    @pytest.mark.asyncio
    async def test_config_requires_auth(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 401
