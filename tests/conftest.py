# stock-monitor/tests/conftest.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.base import Base
from backend.db.database import get_db
from backend.main import app

# 测试用内存数据库
TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_async_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


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
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
