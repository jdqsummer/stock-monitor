# stock-monitor/tests/conftest.py
import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 测试环境标记：DbLogHandler.emit() 据此跳过 DB 写入，避免 lifespan 测试里挂载的
# handler 产生后台 task 干扰其它 test。必须在 import backend.config（加载 settings）前设置。
os.environ["ENVIRONMENT"] = "test"

from backend.db import database as db_module
from backend.db.base import Base
from backend.db.database import get_db
from backend.main import app

# 测试用内存数据库
TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_async_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def _dispose_test_engine():
    """Dispose the in-memory engine after the session.

    Without this, aiosqlite's non-daemon worker threads keep the interpreter
    alive and `pytest` never exits after the suite finishes.
    """
    yield
    asyncio.run(test_engine.dispose())


async def override_get_db():
    async with test_async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    # 创表前先确保所有 model 都已 import（Base.metadata 才会包含 system_logs）
    from backend.models import system_log  # noqa: F401  → 注册 SystemLog
    # 关键：把全局 db_module.async_session_factory 指向测试 engine，
    # 否则 DbLogHandler（直接在模块 import 时就捕获的引用）会用真实 DB 写日志。
    original_factory = db_module.async_session_factory
    db_module.async_session_factory = test_async_session_factory
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
    finally:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        db_module.async_session_factory = original_factory


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
def mock_redis():
    """Mock Redis — 开发阶段无需真实 Redis"""
    mock_redis_client = AsyncMock()
    mock_redis_client.setex = AsyncMock()
    mock_redis_client.get = AsyncMock(return_value="000000")  # 字符串，匹配 decode_responses=True
    mock_redis_client.delete = AsyncMock()
    mock_redis_client.exists = AsyncMock(return_value=0)  # Redis exists returns int, 0 = not exist

    with patch("backend.services.auth_svc._get_redis", return_value=mock_redis_client):
        yield mock_redis_client


# ── westock client fixture ──

from backend.data.westock_client import WestockClient


@pytest_asyncio.fixture
async def westock_client():
    client = WestockClient()  # 使用模拟数据模式
    yield client
    await client.close()


# ── 数据库 session fixture ──

@pytest_asyncio.fixture
async def db_session():
    """提供独立的测试数据库 session"""
    async with test_async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_session_factory():
    """可注入 AnalysisJobService 的 session 工厂（绑定测试引擎）"""
    return test_async_session_factory
