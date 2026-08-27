"""管理后台 API 测试：用户列表 / 系统日志 / 客户端上报 + 鉴权边界。"""
import asyncio
import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.models.system_log import SystemLog
from backend.models.user import User
from backend.services.auth_svc import AuthService


def _headers(user: User) -> dict:
    token = AuthService.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def normal_user(db_session) -> User:
    u = User(
        email="normal-user@example.com",
        password_hash=AuthService.hash_password("pass1234"),
        email_verified=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    u = User(
        email=settings.ADMIN_EMAIL,  # 1140467720@qq.com
        password_hash=AuthService.hash_password("admin-pass"),
        email_verified=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest_asyncio.fixture
async def second_user(db_session) -> User:
    u = User(
        email="second@example.com",
        password_hash=AuthService.hash_password("pass1234"),
        email_verified=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


class TestAdminAuth:
    @pytest.mark.asyncio
    async def test_list_users_requires_auth(self, client: AsyncClient):
        """未认证 → 401"""
        resp = await client.get("/api/admin/users")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_users_non_admin_forbidden(self, client: AsyncClient, normal_user: User):
        """非管理员 → 403（不是 401：必须已登录但权限不足）"""
        resp = await client.get("/api/admin/users", headers=_headers(normal_user))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "仅管理员可访问"

    @pytest.mark.asyncio
    async def test_list_logs_non_admin_forbidden(self, client: AsyncClient, normal_user: User):
        resp = await client.get("/api/admin/logs", headers=_headers(normal_user))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_report_log_non_admin_forbidden(self, client: AsyncClient, normal_user: User):
        resp = await client.post("/api/admin/logs", headers=_headers(normal_user), json={
            "level": "error", "message": "should not be allowed",
        })
        assert resp.status_code == 403


class TestAdminUsers:
    @pytest.mark.asyncio
    async def test_list_users_ok(self, client: AsyncClient, admin_user: User, normal_user: User, second_user: User):
        """管理员可看到全部用户，is_admin 标记正确"""
        resp = await client.get("/api/admin/users", headers=_headers(admin_user))
        assert resp.status_code == 200
        data = resp.json()["data"]
        emails = {u["email"] for u in data}
        assert settings.ADMIN_EMAIL in emails
        assert "normal-user@example.com" in emails
        assert "second@example.com" in emails

        # 找 admin 项
        admin_row = next(u for u in data if u["email"] == settings.ADMIN_EMAIL)
        assert admin_row["is_admin"] is True
        normal_row = next(u for u in data if u["email"] == "normal-user@example.com")
        assert normal_row["is_admin"] is False

    @pytest.mark.asyncio
    async def test_list_users_does_not_leak_password(self, client: AsyncClient, admin_user: User):
        """绝对不能返回 password_hash 字段"""
        resp = await client.get("/api/admin/users", headers=_headers(admin_user))
        assert resp.status_code == 200
        for u in resp.json()["data"]:
            assert "password" not in u
            assert "password_hash" not in u

    @pytest.mark.asyncio
    async def test_last_login_at_visible(
        self, client: AsyncClient, admin_user: User, normal_user: User, db_session,
    ):
        """last_login_at 字段被正确序列化"""
        normal_user.last_login_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        await db_session.commit()
        resp = await client.get("/api/admin/users", headers=_headers(admin_user))
        row = next(u for u in resp.json()["data"] if u["email"] == "normal-user@example.com")
        assert row["last_login_at"] is not None
        # M2：naive UTC 补 +00:00 序列化为 ISO，前端 dayjs 按本地时区展示不再偏移 8h
        assert row["last_login_at"] == "2026-01-01T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_last_login_at_null_for_never_logged_in(
        self, client: AsyncClient, admin_user: User, normal_user: User,
    ):
        resp = await client.get("/api/admin/users", headers=_headers(admin_user))
        row = next(u for u in resp.json()["data"] if u["email"] == "normal-user@example.com")
        assert row["last_login_at"] is None


class TestAdminLogs:
    @pytest.mark.asyncio
    async def test_report_log_persists(
        self, client: AsyncClient, admin_user: User, db_session,
    ):
        """客户端日志上报 → DB 落库一条 system_logs 记录"""
        resp = await client.post("/api/admin/logs",
            headers=_headers(admin_user),
            json={
                "level": "error",
                "message": "frontend test error",
                "source": "/admin",
                "path": "/admin",
                "method": "GET",
                "status_code": 502,
            },
        )
        assert resp.status_code == 200

        # insert 内已同步 commit，返回 200 即已落库，无需等待异步
        rows = (await db_session.execute(
            __import__("sqlalchemy").select(SystemLog).where(SystemLog.message == "frontend test error")
        )).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.level == "error"
        assert row.source == "/admin"
        assert row.email == settings.ADMIN_EMAIL
        assert row.user_id == admin_user.id
        # M1：method/status_code 前端已发送，后端不再丢弃
        assert row.method == "GET"
        assert row.status_code == 502

    @pytest.mark.asyncio
    async def test_list_logs_with_filters(
        self, client: AsyncClient, admin_user: User, db_session,
    ):
        """日志列表 + 筛选：level + source + email + 时间范围"""
        from sqlalchemy import select
        # 准备 3 条
        for lvl, msg in [("error", "boom1"), ("info", "ok1"), ("error", "boom2")]:
            db_session.add(SystemLog(
                id="log-" + msg, level=lvl, source="test.module",
                message=msg, user_id=admin_user.id, email=admin_user.email,
            ))
        await db_session.commit()

        # 按 level=error 过滤
        resp = await client.get("/api/admin/logs",
            headers=_headers(admin_user),
            params={"levels": "error,critical", "limit": 50},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        msgs = {it["message"] for it in body["items"]}
        assert "boom1" in msgs and "boom2" in msgs
        assert "ok1" not in msgs

        # 按 email 模糊
        resp = await client.get("/api/admin/logs",
            headers=_headers(admin_user),
            params={"email": "1140", "limit": 50},
        )
        assert resp.json()["data"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_logs_pagination(
        self, client: AsyncClient, admin_user: User, db_session,
    ):
        """分页：offset/limit 正常返回 total/items"""
        # 准备 5 条
        for i in range(5):
            db_session.add(SystemLog(
                id=f"page-{i}", level="info", source="t", message=f"m{i}",
            ))
        await db_session.commit()

        resp = await client.get("/api/admin/logs",
            headers=_headers(admin_user),
            params={"offset": 0, "limit": 2},
        )
        body = resp.json()["data"]
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert body["total"] >= 5
        assert len(body["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_logs_order_desc(
        self, client: AsyncClient, admin_user: User, db_session,
    ):
        """按 created_at 倒序"""
        db_session.add(SystemLog(id="old", level="info", source="t", message="old"))
        await db_session.commit()
        await asyncio.sleep(0.02)
        db_session.add(SystemLog(id="new", level="info", source="t", message="new"))
        await db_session.commit()

        resp = await client.get("/api/admin/logs",
            headers=_headers(admin_user),
            params={"source": "t", "limit": 50},
        )
        msgs = [it["message"] for it in resp.json()["data"]["items"]]
        assert msgs.index("new") < msgs.index("old")

    @pytest.mark.asyncio
    async def test_cleanup_removes_only_expired(self, db_session):
        """I3：delete_older_than 只删超过保留期的日志，保留期内的不动"""
        from datetime import timedelta

        from sqlalchemy import select

        from backend.services.log_svc import LogService

        now_naive_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.add(SystemLog(
            id="expired-1", level="error", source="t", message="old",
            created_at=now_naive_utc - timedelta(days=40),
        ))
        db_session.add(SystemLog(
            id="fresh-1", level="error", source="t", message="new",
            created_at=now_naive_utc,
        ))
        await db_session.commit()

        removed = await LogService.delete_older_than(db_session, days=30)
        assert removed == 1
        remaining = (await db_session.execute(select(SystemLog))).scalars().all()
        assert [r.id for r in remaining] == ["fresh-1"]


class TestDbLogHandler:
    @pytest.mark.asyncio
    async def test_logger_warning_persists(
        self, db_session, monkeypatch,
    ):
        """模拟 logger.warning 走 DbLogHandler 落库（I3 后采集级别为 WARNING）"""
        from backend.services import log_handler
        # 用直接调用的方式避开 create_task（测试环境事件循环与 install 路径一致）
        record = logging.LogRecord(
            name="test.module", level=logging.WARNING,
            pathname=__file__, lineno=0,
            msg="hello %s", args=("world",), exc_info=None,
        )
        await log_handler.DbLogHandler()._async_emit(record)

        rows = (await db_session.execute(
            __import__("sqlalchemy").select(SystemLog).where(SystemLog.message == "hello world")
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].level == "warning"
        assert rows[0].source == "test.module"

    @pytest.mark.asyncio
    async def test_logger_with_extras(
        self, db_session, monkeypatch,
    ):
        """logger.error(extra={'user_id': ..., 'path': ...}) 应正确入 user_id/path 列"""
        from backend.services import log_handler
        record = logging.LogRecord(
            name="test.x", level=logging.ERROR,
            pathname=__file__, lineno=0,
            msg="err", args=None, exc_info=None,
        )
        record.user_id = "uid-123"
        record.path = "/api/foo"
        record.method = "POST"
        record.status_code = 500
        await log_handler.DbLogHandler()._async_emit(record)

        rows = (await db_session.execute(
            __import__("sqlalchemy").select(SystemLog).where(SystemLog.message == "err")
        )).scalars().all()
        assert len(rows) == 1
        r = rows[0]
        assert r.user_id == "uid-123"
        assert r.path == "/api/foo"
        assert r.method == "POST"
        assert r.status_code == 500


class TestE2ELogPersistence:
    @pytest.mark.asyncio
    async def test_unhandled_exception_persists_with_stack_trace(
        self, db_session, monkeypatch,
    ):
        """端到端：install() 无条件挂载（C1）+ 异常处理器传 exc_info（I1）
        → 5xx 经 logger → system_logs 落库一条带 stack_trace 的记录。

        此前 ENABLE_DB_LOG_HANDLER 门控导致生产默认不挂载，这条链路整体 no-op。
        ASGITransport 不跑 lifespan，故手动 install() 模拟生产启动路径。
        """
        from sqlalchemy import select

        from backend.main import app
        from backend.services.log_handler import install as install_log_handler

        # 模拟 lifespan：install() 在测试环境也会挂载（emit 内部才跳过）；临时解除测试跳过
        install_log_handler()
        monkeypatch.setattr("backend.config.settings.ENVIRONMENT", "production")

        async def _boom():
            raise RuntimeError("boom-e2e-log")

        app.add_api_route("/api/_test_boom", _boom, methods=["GET"])
        try:
            # ServerErrorMiddleware 处理完 500 后仍会 re-raise（供服务器/测试客户端记录异常），
            # 因此用 raise_app_exceptions=False 才能取到 500 响应体；落库已在 handler 内完成。
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/_test_boom")
            assert resp.status_code == 500
            assert resp.json()["detail"] == "服务器内部错误"

            # emit 走 create_task 异步写库 → 轮询等待落库完成
            row = None
            for _ in range(20):
                await asyncio.sleep(0.05)
                rows = (await db_session.execute(
                    select(SystemLog).where(SystemLog.message.contains("boom-e2e-log"))
                )).scalars().all()
                if rows:
                    row = rows[0]
                    break
            assert row is not None, "未捕获异常日志未落库（C1 默认挂载失效）"
            assert row.level == "critical"
            assert row.source == "backend.main"
            assert "RuntimeError" in row.message
            assert row.stack_trace is not None and "boom-e2e-log" in row.stack_trace
            assert row.path == "/api/_test_boom"
            assert row.status_code == 500
        finally:
            # 移除临时路由，避免污染后续测试
            app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/api/_test_boom"]
