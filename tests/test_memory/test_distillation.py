import pytest

from backend.memory.store import MemoryStore
from backend.memory.distillation import DistillationPipeline


@pytest.mark.asyncio
async def test_distill_conversation_extracts_L1(db_session):
    """蒸馏对话生成 L1 记忆（Mock LLM）"""
    pipeline = DistillationPipeline(llm_model="mock")
    result = await pipeline.distill_conversation(
        db_session, "user1",
        "用户：我关注半导体行业，特别是设备厂商。最近在看北方华创。\n"
        "Agent：好的，我分析一下。注意设备行业周期性强。"
    )
    assert isinstance(result, dict)
    assert "L1" in result
    assert "L2" in result


@pytest.mark.asyncio
async def test_build_L3_profile_no_data(db_session):
    """无 L1/L2 数据时 L3 画像不生成"""
    pipeline = DistillationPipeline(llm_model="mock")
    profile = await pipeline.build_L3_profile(db_session, "new_user")
    assert profile == "暂无足够数据"


@pytest.mark.asyncio
async def test_build_L3_profile_with_data(db_session):
    """有数据时生成 L3 画像"""
    await MemoryStore.save_memory(db_session, "user1", "L1", "关注行业", "半导体和白酒")
    await MemoryStore.save_memory(db_session, "user1", "L1", "偏好", "偏好大盘蓝筹")
    await MemoryStore.save_memory(db_session, "user1", "L2", "策略", "分批建仓，低估买入")

    pipeline = DistillationPipeline(llm_model="mock")
    profile = await pipeline.build_L3_profile(db_session, "user1")
    assert len(profile) > 0
    assert profile != "暂无足够数据"
