# tests/test_services/test_chat_agent_loop.py
"""聊天 Agent Loop（function calling 编排）— TDD"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm.provider import LLMResponse
from backend.services.chat_agent_loop import ChatAgentLoop, MAX_TOOL_ROUNDS, _ToolCallXmlStripper


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


def test_tool_call_xml_stripper():
    """stripper 过滤 <tool_calls>/<invoke> XML，保留正常文本"""
    s = _ToolCallXmlStripper()
    assert s.feed("贵州茅台现价 1340 元。") == "贵州茅台现价 1340 元。"
    # 单 chunk 完整块被整体移除，前后文本保留
    out = s.feed("结论：<tool_calls> <invoke name=\"get_financials_detail\"> <parameter name=\"code\">01810.HK</parameter> </invoke> </tool_calls> 财报见上。")
    assert out == "结论： 财报见上。"
    assert "tool_calls" not in out and "invoke" not in out


def test_tool_call_xml_stripper_cross_chunk():
    """标记跨多个 chunk 分片时仍有状态地过滤（不把分片漏出）"""
    s = _ToolCallXmlStripper()
    assert s.feed("开头 ") == "开头 "
    assert s.feed("<tool_calls> <invoke") == ""  # 进入抑制态，不输出分片
    assert s.feed(" name=\"x\">...") == ""
    assert s.feed("</invoke> </tool_calls>") == ""
    assert s.feed(" 结尾") == " 结尾"


def test_tool_call_xml_stripper_micro_split():
    """DeepSeek 流式把标记拆成 2-4 字节微块（< + tool + _c + alls + >）也能过滤——生产实测泄漏场景"""
    s = _ToolCallXmlStripper()
    out = ""
    for frag in ["<", "tool", "_c", "alls", ">\n", "<invoke", " name=\"x\">", "aa",
                 "</", "invoke", ">", " ", "</", "tool", "_c", "alls", ">", " 正文"]:
        out += s.feed(frag)
    assert "tool_calls" not in out and "invoke" not in out
    assert "正文" in out


def test_tool_call_xml_stripper_micro_split_leading_text():
    """微块分片 + 前置文本：前置文本保留，标记整块过滤"""
    s = _ToolCallXmlStripper()
    out = ""
    for frag in ["结论", "：", "<", "tool", "_c", "alls", ">", "<invoke", " n=", "\"x\"", ">",
                 "</invoke>", "</", "tool", "_c", "alls", ">", "，数据如下", "。"]:
        out += s.feed(frag)
    assert "tool_calls" not in out and "invoke" not in out
    assert out.startswith("结论：")
    assert "，数据如下。" in out


def test_tool_call_xml_stripper_fullwidth_bar_variant():
    """生产实测：DeepSeek 用全角竖线 ｜｜ 的变体标记 <｜｜tool_calls>...</｜｜tool_calls> 也须过滤"""
    s = _ToolCallXmlStripper()
    out = ""
    frags = ["开头 ", "<", "｜", "｜", "tool", "_c", "alls", ">",
             "<｜｜invoke", " name=\"get_financials\">",
             "<｜｜parameter", " name=\"code\"", " string=\"true\">", "01810.HK",
             "</", "｜", "｜", "parameter", ">",
             "</", "｜", "｜", "invoke", ">",
             "</", "｜", "｜", "tool", "_c", "alls", ">", " 结尾"]
    for f in frags:
        out += s.feed(f)
    assert "tool_calls" not in out and "｜｜" not in out
    assert out == "开头  结尾"


@pytest.mark.asyncio
async def test_run_stream_filters_tool_call_xml_from_chunks():
    """模型把伪调用 XML 当正文流式输出 → chunk 事件不含 XML，正常文本保留"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=LLMResponse(content="", model="mock", raw_response=None))
    async def _chat_stream(messages, tools=None):
        for c in ["<tool_calls> <invoke name=\"get_financials_detail\"> <parameter name=\"code\">01810.HK</parameter> </invoke> </tool_calls>", "小米财报如下：营收 3659 亿。"]:
            yield c
    llm.chat_stream = _chat_stream
    db = AsyncMock()
    db.add = MagicMock()
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        chunks = []
        async for ev in loop.run_stream("u1", "小米财报"):
            if ev["event"] == "chunk":
                chunks.append(ev["data"]["content"])
    joined = "".join(chunks)
    assert "tool_calls" not in joined and "invoke" not in joined
    assert "小米财报如下：营收 3659 亿" in joined


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
async def test_save_conversation_strips_tool_call_placeholders():
    """工具调用轮的中间消息（content=None 的 assistant tool_calls 占位 / role=tool 结果）
    不应持久化到历史 —— 历史仅保留 user + 助手正文回复，否则前端加载历史时会把占位
    消息渲染成「空助手气泡」（只有最后一条完整、其余为空数据）。

    回归：修复前 stored = [user, assistant(content=None, tool_calls), tool, assistant(text)]，
    前端按 role 过滤后出现 content=None 的空助手消息。
    """
    llm = _llm_with_tool_call_then_text()
    db = AsyncMock()
    saved: dict = {}
    def _capture_add(conv):
        saved["conv"] = conv
    db.add = MagicMock(side_effect=_capture_add)
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
        async for _ in loop.run_stream("u1", "分析 600519"):
            pass

    conv = saved.get("conv")
    assert conv is not None
    msgs = conv.messages
    # 无 role=tool 中间结果
    assert not any(m.get("role") == "tool" for m in msgs)
    # 无 content 为空/None 的 assistant 占位
    assert not any(m.get("role") == "assistant" and not m.get("content") for m in msgs)
    # 恰好一条助手正文回复，含流式文本
    assistants = [m for m in msgs if m["role"] == "assistant"]
    assert len(assistants) == 1
    assert "现价 1500" in assistants[0]["content"]
    # 结构为 user → assistant 交替（首条 user）
    assert msgs[0]["role"] == "user"
    assert msgs[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_run_stream_tool_result_with_datetime_does_not_crash():
    """工具结果含 datetime 等非 JSON 可序列化值 → json.dumps(default=str) 兜底，不产 error 事件"""
    from datetime import datetime

    llm = _llm_with_tool_call_then_text()
    db = AsyncMock()
    db.add = MagicMock()
    with patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.execute_tool",
               AsyncMock(return_value={"code": "600519", "name": "贵州茅台",
                                       "update_time": datetime(2026, 8, 22, 15, 0)})), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        events = []
        async for ev in loop.run_stream("u1", "分析 600519"):
            events.append(ev)

    ev_types = [e["event"] for e in events]
    assert "error" not in ev_types
    assert "done" in ev_types


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
async def test_run_stream_llm_timeout_yields_error_then_done():
    """LLM 调用超时 → 产出 error（含超时提示）+ done，会话仍保存不静默挂起。

    LLM_TIMEOUT_SECONDS 接线回归：llm.chat 挂起时 asyncio.timeout 触发 TimeoutError，
    run_stream 应产出 error 事件（不静默 hang），并继续保存会话产出 done。
    """
    async def _hang(messages, tools=None, tool_choice="auto"):
        await asyncio.sleep(10)

    llm = MagicMock()
    llm.chat = _hang

    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add 是同步方法
    with patch("backend.services.chat_agent_loop.settings.LLM_TIMEOUT_SECONDS", 0.05), \
         patch("backend.services.chat_agent_loop.load_chat_persona",
               return_value="你是投资助手"), \
         patch("backend.services.chat_agent_loop.build_chat_context",
               AsyncMock(return_value={"summary_positions": "", "summary_watchlist": "",
                                       "summary_diary": "", "memories": {}})), \
         patch("backend.services.chat_agent_loop.MemoryService") as ms:
        ms.return_value.distill_async = MagicMock()
        loop = ChatAgentLoop(llm_provider=llm, db=db)
        events = [e async for e in loop.run_stream("u1", "你好")]

    ev_types = [e["event"] for e in events]
    assert "error" in ev_types
    assert "done" in ev_types
    err = next(e for e in events if e["event"] == "error")
    assert "超时" in err["data"]["message"]


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
