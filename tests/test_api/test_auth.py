# stock-monitor/tests/test_api/test_auth.py
import pytest
from httpx import AsyncClient


async def _register_user(client: AsyncClient, email: str, password: str):
    """Helper: 完整注册流程（mock Redis 验证码）"""
    # 发送验证码
    resp = await client.post("/api/auth/register/send-code", json={
        "email": email,
        "purpose": "register",
    })
    assert resp.status_code == 200

    # 注册（验证码已 mock 为总是通过）
    resp = await client.post("/api/auth/register", json={
        "email": email,
        "code": "000000",
        "password": password,
    })
    return resp


async def _login_user(client: AsyncClient, email: str, password: str) -> str:
    """Helper: 登录获取 token"""
    resp = await client.post("/api/auth/login", json={
        "email": email,
        "password": password,
    })
    data = resp.json()
    return data["data"]["access_token"]


class TestAuth:
    @pytest.mark.asyncio
    async def test_send_register_code(self, client, mock_redis):
        """发送注册验证码"""
        resp = await client.post("/api/auth/register/send-code", json={
            "email": "newuser@example.com",
            "purpose": "register",
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "验证码已发送"

    @pytest.mark.asyncio
    async def test_register_and_login(self, client, mock_redis):
        """完整注册 + 密码登录流程"""
        # 注册
        resp = await _register_user(client, "user1@example.com", "testpass123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["message"] == "注册成功"
        assert "access_token" in data["data"]

        # 用密码登录
        resp = await client.post("/api/auth/login", json={
            "email": "user1@example.com",
            "password": "testpass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, mock_redis):
        """密码错误应拒绝"""
        await _register_user(client, "user2@example.com", "testpass123")
        resp = await client.post("/api/auth/login", json={
            "email": "user2@example.com",
            "password": "wrongpass",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_duplicate_registration(self, client, mock_redis):
        """重复注册应返回 409（send-code 提前提示已注册，register 端也拒绝）"""
        await _register_user(client, "user3@example.com", "testpass123")
        # 已注册邮箱再发验证码 → 409 提示已注册，引导登录
        resp = await client.post("/api/auth/register/send-code", json={
            "email": "user3@example.com",
            "purpose": "register",
        })
        assert resp.status_code == 409
        assert resp.json()["detail"] == "该邮箱已注册，请直接登录"
        # 直接再次注册 → 仍 409
        resp2 = await client.post("/api/auth/register", json={
            "email": "user3@example.com",
            "code": "000000",
            "password": "testpass123",
        })
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_get_me_authenticated(self, client, mock_redis):
        """认证后可获取用户信息"""
        await _register_user(client, "user4@example.com", "testpass123")
        token = await _login_user(client, "user4@example.com", "testpass123")

        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["email"] == "user4@example.com"

    @pytest.mark.asyncio
    async def test_get_me_unauthenticated(self, client):
        """未认证应拒绝"""
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_by_code_send(self, client, mock_redis):
        """发送登录验证码"""
        resp = await client.post("/api/auth/login/send-code", json={
            "email": "user5@example.com",
            "purpose": "login",
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "验证码已发送"

    @pytest.mark.asyncio
    async def test_login_by_code(self, client, mock_redis):
        """验证码登录"""
        await _register_user(client, "user6@example.com", "testpass123")

        resp = await client.post("/api/auth/login/code", json={
            "email": "user6@example.com",
            "code": "000000",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]

    @pytest.mark.asyncio
    async def test_send_reset_code(self, client, mock_redis):
        """已注册邮箱发送重置验证码"""
        await _register_user(client, "reset1@example.com", "oldpass123")
        resp = await client.post("/api/auth/password/send-code", json={
            "email": "reset1@example.com",
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "验证码已发送"

    @pytest.mark.asyncio
    async def test_send_reset_code_unregistered(self, client, mock_redis):
        """未注册邮箱发送重置验证码 → 409"""
        resp = await client.post("/api/auth/password/send-code", json={
            "email": "nobody@example.com",
        })
        assert resp.status_code == 409
        assert resp.json()["detail"] == "该邮箱未注册，请先注册"

    @pytest.mark.asyncio
    async def test_reset_password(self, client, mock_redis):
        """重置密码后旧密码失效、新密码可登录"""
        await _register_user(client, "reset2@example.com", "oldpass123")
        resp = await client.post("/api/auth/password/reset", json={
            "email": "reset2@example.com",
            "code": "000000",
            "new_password": "newpass456",
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "密码重置成功"
        # 旧密码登录失败
        old = await client.post("/api/auth/login", json={
            "email": "reset2@example.com",
            "password": "oldpass123",
        })
        assert old.status_code == 401
        # 新密码登录成功
        new = await client.post("/api/auth/login", json={
            "email": "reset2@example.com",
            "password": "newpass456",
        })
        assert new.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_wrong_code(self, client, mock_redis):
        """验证码错误 → 400"""
        await _register_user(client, "reset3@example.com", "oldpass123")
        resp = await client.post("/api/auth/password/reset", json={
            "email": "reset3@example.com",
            "code": "999999",
            "new_password": "newpass456",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_send_code_rate_limit(self, client, mock_redis):
        """重置验证码发送限频 → 429"""
        from unittest.mock import AsyncMock
        await _register_user(client, "reset4@example.com", "oldpass123")
        mock_redis.exists = AsyncMock(return_value=1)  # 注册完成后再开限频
        resp = await client.post("/api/auth/password/send-code", json={
            "email": "reset4@example.com",
        })
        assert resp.status_code == 429
