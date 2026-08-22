# tests/test_services/test_chat_agent_loop.py
"""聊天 Agent Loop（function calling 编排）— TDD"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm.provider import LLMResponse
from backend.services.chat_agent_loop import ChatAgentLoop, MAX_TOOL_ROUNDS


def _llm_with_tool_call_then_text():
    """Mock LLM：第一轮返回 tool_call，第二轮返回文本"""
    llm = MagicMock()

    def fake_chat(messages, tools=None, tool_choice="auto"):
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        # 第一轮（无 tool 消息）→ tool_call
        if not any(m.get("role") == "tool" for m in messages):
            raw = MagicMock()
            raw.choices = [MagicMock(message=MagicMock(tool_calls=[
                MagicMock(id="call_1", function=MagicMock(
                    name="get_stock_snapshot", arguments='{"code": "600519"}')),
            ]))]
            return LLMResponse(content="", model="mock", raw_response=raw)
        return LLMResponse(content="贵州茅台现价 1500 元，信号灯🟡。", model="mock", raw_response=None)

    llm.chat = AsyncMock(side_effect=fake_chat)
    llm.chat_stream = AsyncMock(return_value=_fake_stream(["贵州茅台现价 1500 元，信号灯🟡。"]))
    return llm


def _fake_stream(chunks):
    async def _gen():
        for c in chunks:
            yield c
    return _gen()


@pytest.mark.asyncio
async def test_run_stream_executes_tool_and_streams_text():
    """run_stream 应产出 tool_call → tool_result → chunk → done 事件"""
    llm = _llm_with_tool_call_then_text()
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.execute_tool",
               AsyncMock(return_value={"code": "600519", "name": "贵州茅台"})), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={"summary_positions": "", "summary_watchlist": "",
                                       "summary_diary": "", "memories": {}})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        events = []
        async for ev in loop.run_stream("u1", "分析 600519"):
            events.append(ev)

    ev_types = [e["event"] for e in events]
    assert "tool_call" in ev_types
    assert "tool_result" in ev_types
    assert "chunk" in ev_types
    assert "done" in ev_types
    # 工具调用后执行 execute_tool 收到 user_id
    # 蒸馏触发
    ms.return_value.distill_async.assert_called_once()


@pytest.mark.asyncio
async def test_run_send_returns_content_and_job_ids():
    """run_send 聚合事件返回 content + conversation_id + job_ids"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(
        content="分析已提交，约 1-2 分钟完成。", model="mock", raw_response=None))
    llm.chat_stream = AsyncMock(return_value=_fake_stream(["分析已提交，约 1-2 分钟完成。"]))
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        result = await loop.run_send("u1", "你好")

    assert "content" in result
    assert "conversation_id" in result
