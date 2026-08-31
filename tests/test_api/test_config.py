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


def _default_payload():
    return {
        "llm_model": "openrouter:minimax/minimax-m3:free",
        "data_refresh_interval_minutes": 30,
        "analysis_schedule_afternoon": "16:00",
        "analysis_auto_enabled": False,
        "analysis_concurrency": 3,
        "notification_enabled": False,
        "reminder_email_enabled": False,
        "reminder_bell_enabled": False,
    }


class TestConfig:
    @pytest.mark.asyncio
    async def test_get_default_config(self, client):
        token = await _register_and_login(client, "cfg_default@example.com")
        resp = await client.get("/api/config", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["llm_model"] == "openrouter:minimax/minimax-m3:free"
        assert data["data"]["analysis_concurrency"] == 3
        assert data["data"]["analysis_schedule_afternoon"] == "16:00"
        assert "llm_temperature" not in data["data"]
        assert "investment_style" not in data["data"]
        assert "westock_api_key" not in data["data"]

    @pytest.mark.asyncio
    async def test_update_config(self, client):
        token = await _register_and_login(client, "cfg_update@example.com")
        new_config = {
            **_default_payload(),
            "llm_model": "deepseek-v4-pro",
            "data_refresh_interval_minutes": 15,
            "analysis_schedule_afternoon": "16:30",
            "analysis_concurrency": 5,
            "notification_enabled": True,
            "analysis_auto_enabled": True,
        }
        resp = await client.put("/api/config", json=new_config, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["llm_model"] == "deepseek-v4-pro"
        assert data["data"]["analysis_concurrency"] == 5
        assert data["data"]["notification_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_config_persists_analysis_auto_enabled(self, client, db_session):
        """分析开关应持久化：PUT → GET 回显 → 库中 user.config JSON 均可见"""
        email = "cfg_auto_analysis@example.com"
        token = await _register_and_login(client, email)
        new_config = {**_default_payload(), "notification_enabled": True, "analysis_auto_enabled": True}
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
    async def test_get_config_key_masked(self, client):
        """GET 不回显 key 明文：仅回传掩码 + configured 布尔"""
        token = await _register_and_login(client, "cfg_mask@example.com")
        resp = await client.get("/api/config", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"]["deepseek_api_key"] is None
        assert resp.json()["data"]["deepseek_api_key_configured"] is False
        assert resp.json()["data"]["smtp_password"] is None
        assert resp.json()["data"]["smtp_password_configured"] is False

    @pytest.mark.asyncio
    async def test_update_config_empty_key_keeps_old(self, client, db_session):
        """空串 key 不覆盖已存 key"""
        email = "cfg_keykeep@example.com"
        token = await _register_and_login(client, email)
        base = {k: v for k, v in _default_payload().items()}
        base.update({"deepseek_api_key": "sk-old"})
        await client.put("/api/config", json=base, headers={"Authorization": f"Bearer {token}"})
        resp = await client.put("/api/config", json={**base, "deepseek_api_key": ""},
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["data"]["deepseek_api_key_configured"] is True
        result = await db_session.execute(select(User).where(User.email == email))
        assert result.scalar_one().config["deepseek_api_key"] == "sk-old"

    @pytest.mark.asyncio
    async def test_get_llm_models(self, client):
        resp = await client.get("/api/config/llm-models")
        assert resp.status_code == 200
        data = resp.json()
        models = data["data"]
        assert len(models) == 9
        providers = {m["provider"] for m in models}
        assert "openrouter" in providers
        assert "deepseek" in providers
        assert "qwen" in providers
        assert "kimi" in providers

    @pytest.mark.asyncio
    async def test_update_config_triggers_reconcile(self, client, monkeypatch):
        """保存配置后触发 app.state.reconcile_all（即时对齐 per-user job，无需重启）"""
        from unittest.mock import AsyncMock

        from backend.main import app

        token = await _register_and_login(client, "cfg_reconcile@example.com")
        reconcile = AsyncMock()
        monkeypatch.setattr(app.state, "reconcile_all", reconcile, raising=False)
        resp = await client.put("/api/config", json=_default_payload(),
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        reconcile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_config_requires_auth(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 401
