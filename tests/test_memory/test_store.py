import pytest

from backend.memory.store import MemoryStore


@pytest.mark.asyncio
async def test_save_and_get_memory(db_session):
    """保存并检索记忆"""
    mem = await MemoryStore.save_memory(
        db_session, "user1", "L1", "关注行业", "用户关注半导体和白酒行业",
        source="analysis_001", confidence=0.9,
    )
    assert mem.id is not None
    assert mem.level == "L1"

    memories = await MemoryStore.get_memories(db_session, "user1", level="L1")
    assert len(memories) >= 1
    assert memories[0].content == "用户关注半导体和白酒行业"


@pytest.mark.asyncio
async def test_get_memories_by_category(db_session):
    """按 category 过滤"""
    await MemoryStore.save_memory(db_session, "user1", "L1", "偏好", "偏好A")
    await MemoryStore.save_memory(db_session, "user1", "L1", "策略", "策略B")

    result = await MemoryStore.get_memories(db_session, "user1", level="L1", category="偏好")
    assert len(result) == 1
    assert result[0].content == "偏好A"


@pytest.mark.asyncio
async def test_upsert_memory(db_session):
    """Upsert：同 category 更新而非新增"""
    await MemoryStore.save_memory(db_session, "user1", "L1", "风险", "保守", confidence=0.5)
    await MemoryStore.upsert_memory_by_category(db_session, "user1", "L1", "风险", "激进", confidence=0.9)

    results = await MemoryStore.get_memories(db_session, "user1", level="L1", category="风险")
    assert len(results) == 1
    assert results[0].content == "激进"
    assert results[0].confidence == 0.9


@pytest.mark.asyncio
async def test_save_conversation(db_session):
    """保存 L0 对话"""
    conv = await MemoryStore.save_conversation(
        db_session, "user1", "chat",
        messages=[{"role": "user", "content": "分析茅台"}, {"role": "assistant", "content": "..."}],
        summary="用户询问茅台分析",
    )
    assert conv.id is not None

    convs = await MemoryStore.get_conversations(db_session, "user1")
    assert len(convs) >= 1
    assert convs[0].agent_type == "chat"


@pytest.mark.asyncio
async def test_delete_memory(db_session):
    """删除记忆"""
    mem = await MemoryStore.save_memory(db_session, "user1", "L1", "临时", "删除我")
    deleted = await MemoryStore.delete_memory(db_session, mem.id)
    assert deleted is True

    result = await MemoryStore.get_memories(db_session, "user1", category="临时")
    assert len(result) == 0
