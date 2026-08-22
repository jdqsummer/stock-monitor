"""LLM Provider 流式工具支持 — TDD"""
import json
from types import SimpleNamespace

import pytest

from backend.llm.provider import MockLLMProvider, LLMFactory, LLMConfig, ProviderType


@pytest.mark.asyncio
async def test_chat_stream_accepts_tools_param():
    """chat_stream 应接受可选 tools 参数（向后兼容）"""
    provider = MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    msgs = [{"role": "user", "content": "你好"}]
    chunks = []
    async for c in provider.chat_stream(msgs, tools=[{"type": "function", "function": {"name": "x"}}]):
        chunks.append(c)
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_mock_chat_returns_tool_calls_for_analysis():
    """Mock 在「分析 <6位代码>」时应返回 run_five_stage 工具调用"""
    provider = MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    resp = await provider.chat(
        [{"role": "user", "content": "帮我分析 600519"}],
        tools=[{"type": "function", "function": {"name": "run_five_stage", "parameters": {}}}],
    )
    assert resp.raw_response is not None
    msg = resp.raw_response.choices[0].message
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].function.name == "run_five_stage"
    args = json.loads(msg.tool_calls[0].function.arguments)
    assert args["code"] == "600519"


@pytest.mark.asyncio
async def test_mock_chat_plain_text_without_tools():
    """Mock 不带 tools 或非分析消息 → 纯文本，无 tool_calls"""
    provider = MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    resp = await provider.chat([{"role": "user", "content": "什么是安全边际"}])
    assert resp.raw_response is None
    assert "安全边际" in resp.content


def test_settings_has_chat_timeout_and_persona_path():
    """config 应含 LLM_TIMEOUT_SECONDS 与 CHAT_PERSONA_PATH"""
    from backend.config import settings
    assert settings.LLM_TIMEOUT_SECONDS > 0
    assert settings.CHAT_PERSONA_PATH.endswith("SKILL.md")
