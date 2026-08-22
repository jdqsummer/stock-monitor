# tests/test_services/test_chat_agent_loop.py
"""聊天 Agent Loop（function calling 编排）— TDD"""
from types import SimpleNamespace
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

    # chat_stream 契约：async generator（与各 provider 一致），不可 await。
    # 用真实 async generator 而非 AsyncMock，否则会掩盖 loop 里 `await chat_stream` 的 bug。
    async def _chat_stream(messages, tools=None):
        for c in ["贵州茅台现价 1500 元，信号灯🟡。"]:
            yield c

    llm.chat_stream = _chat_stream
    return llm


def _llm_with_run_five_stage_then_text():
    """Mock LLM：第一轮返回 run_five_stage tool_call，第二轮返回文本。

    用 SimpleNamespace 构造 raw_response，保证 fn.name 为真实字符串
    （MagicMock(name=...) 会让 fn.name 返回子 mock，导致 name 匹配失效）。
    """
    llm = MagicMock()

    def fake_chat(messages, tools=None, tool_choice="auto"):
        # 第一轮（无 tool 消息）→ run_five_stage tool_call
        if not any(m.get("role") == "tool" for m in messages):
            raw = SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(tool_calls=[
                    SimpleNamespace(
                        id="call_1",
                        function=SimpleNamespace(name="run_five_stage",
                                                 arguments='{"code": "600519"}'),
                    ),
                ])),
            ])
            return LLMResponse(content="", model="mock", raw_response=raw)
        return LLMResponse(content="分析已提交，约 1-2 分钟完成。", model="mock", raw_response=None)

    llm.chat = AsyncMock(side_effect=fake_chat)

    async def _chat_stream(messages, tools=None):
        for c in ["分析已提交，约 1-2 分钟完成。"]:
            yield c

    llm.chat_stream = _chat_stream
    return llm


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
async def test_run_stream_run_five_stage_emits_analysis_submitted():
    """run_five_stage 工具结果含 job_id → 产出 analysis_submitted 事件 + 记录 submitted_job_ids"""
    llm = _llm_with_run_five_stage_then_text()
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.execute_tool",
               AsyncMock(return_value={"code": "600519", "job_id": "job_chat_1",
                                       "status": "submitted"})), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={"summary_positions": "", "summary_watchlist": "",
                                       "summary_diary": "", "memories": {}})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        events = []
        async for ev in loop.run_stream("u1", "分析 600519"):
            events.append(ev)

    analysis_events = [e for e in events if e["event"] == "analysis_submitted"]
    assert len(analysis_events) == 1
    assert analysis_events[0]["data"]["job_id"] == "job_chat_1"
    assert analysis_events[0]["data"]["code"] == "600519"
    assert loop.submitted_job_ids == ["job_chat_1"]


@pytest.mark.asyncio
async def test_run_stream_tool_error_still_yields_tool_result():
    """工具抛异常 → 仍产出 tool_result（含失败摘要），且不产出 analysis_submitted"""
    llm = _llm_with_tool_call_then_text()  # 第一轮 get_stock_snapshot tool_call
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.execute_tool",
               AsyncMock(side_effect=RuntimeError("boom"))), \
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
    assert "tool_result" in ev_types
    assert "analysis_submitted" not in ev_types
    tool_result = next(e for e in events if e["event"] == "tool_result")
    assert "失败" in tool_result["data"]["summary"]


@pytest.mark.asyncio
async def test_run_send_returns_content_and_job_ids():
    """run_send 聚合事件返回 content + conversation_id + job_ids"""
    llm = _llm_with_run_five_stage_then_text()
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.execute_tool",
               AsyncMock(return_value={"job_id": "job_send_1"})), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        result = await loop.run_send("u1", "你好")

    assert "content" in result
    assert "conversation_id" in result
    assert result["job_ids"] == ["job_send_1"]


@pytest.mark.asyncio
async def test_run_stream_with_real_async_generator_chat_stream():
    """回归：chat_stream 为真实 async generator 时，run_stream 应产出 chunk+done 而非 error。

    各 provider 的 chat_stream 均为 `async def ... yield`（异步生成器），不可 await。
    曾因 `await self.llm.chat_stream(...)` 抛 `TypeError: object async_generator can't be
    used in 'await' expression`（被 try/except 吞成 error 事件），此测试用真实 async
    generator 守护该契约。
    """
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(
        content="Mock LLM response to: 你好", model="mock", raw_response=None))

    async def _chat_stream(messages, tools=None):
        for c in ["你好，", "我是投资小助手。"]:
            yield c

    llm.chat_stream = _chat_stream

    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={"summary_positions": "", "summary_watchlist": "",
                                       "summary_diary": "", "memories": {}})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        events = [e async for e in loop.run_stream("u1", "你好")]

    ev_types = [e["event"] for e in events]
    assert "chunk" in ev_types
    assert "done" in ev_types
    assert "error" not in ev_types
    text = "".join(e["data"]["content"] for e in events if e["event"] == "chunk")
    assert text == "你好，我是投资小助手。"
