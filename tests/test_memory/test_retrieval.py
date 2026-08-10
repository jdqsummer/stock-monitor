import pytest

from backend.memory.store import MemoryStore
from backend.memory.retrieval import MemoryRetriever


@pytest.mark.asyncio
async def test_retrieve_L1_keyword_match(db_session):
    """L1 检索：关键词匹配评分"""
    await MemoryStore.save_memory(db_session, "user1", "L1", "关注行业", "半导体和白酒行业", confidence=1.0)
    await MemoryStore.save_memory(db_session, "user1", "L1", "偏好", "喜欢消费类龙头", confidence=0.8)

    retriever = MemoryRetriever(db_session, "user1")
    result = await retriever.retrieve("半导体", levels=["L1"])

    assert "L1" in result
    assert len(result["L1"]) >= 1
    assert "半导体" in result["L1"][0]["content"]


@pytest.mark.asyncio
async def test_retrieve_L3_returns_latest(db_session):
    """L3 检索：返回最新一条用户画像"""
    await MemoryStore.save_memory(db_session, "user1", "L3", "投资画像", "保守型投资者", confidence=1.0)
    await MemoryStore.save_memory(db_session, "user1", "L3", "投资画像", "激进型投资者", confidence=0.8)

    retriever = MemoryRetriever(db_session, "user1")
    result = await retriever.retrieve("query", levels=["L3"])

    assert len(result["L3"]) == 1


@pytest.mark.asyncio
async def test_build_context_format(db_session):
    """build_context 输出格式验证"""
    await MemoryStore.save_memory(db_session, "user1", "L3", "投资画像", "价值投资者，风险承受度中等")
    await MemoryStore.save_memory(db_session, "user1", "L1", "偏好", "关注半导体行业")
    await MemoryStore.save_memory(db_session, "user1", "L2", "策略", "偏好分批建仓")

    retriever = MemoryRetriever(db_session, "user1")
    context = await retriever.build_context("半导体投资")

    assert "用户投资画像" in context
    assert "价值投资者" in context
    assert "半导体" in context
