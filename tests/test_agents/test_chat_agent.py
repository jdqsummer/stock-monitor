# tests/test_agents/test_chat_agent.py
"""ChatAgent 单元测试 — TDD RED Phase"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.llm.provider import LLMProvider, LLMResponse, LLMConfig, ProviderType


# ── Helpers ──

def make_mock_llm(response_text: str = "这是测试回复") -> LLMProvider:
    """创建一个 mock LLM provider，返回指定文本"""
    mock = MagicMock(spec=LLMProvider)
    mock.config = LLMConfig(
        provider=ProviderType.MOCK,
        model_id="mock-test",
    )

    resp = LLMResponse(content=response_text, model="mock-test")
    mock.chat = AsyncMock(return_value=resp)

    async def mock_stream(messages):
        for chunk in response_text.split():
            yield chunk + " "

    # chat_stream 是 async 方法，用 AsyncMock
    mock.chat_stream = AsyncMock(return_value=mock_stream([{"role": "user", "content": "test"}]))

    return mock


def make_mock_db_result(scalar_result=None):
    """创建模拟 SQLAlchemy Result 对象"""
    result = MagicMock()
    if scalar_result is not None:
        result.scalar_one_or_none.return_value = scalar_result
        result.scalars.return_value.all.return_value = scalar_result if isinstance(scalar_result, list) else [scalar_result]
    else:
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
    return result


def make_mock_db(conversation_for_load=None):
    """创建一个 mock 数据库 session，可选预设一个加载的对话"""
    mock = AsyncMock(spec=AsyncSession)

    async def mock_execute(stmt):
        result = make_mock_db_result(conversation_for_load)
        return result

    mock.execute = mock_execute
    return mock


# ── Tests ──

class TestChatAgentInit:
    """ChatAgent 初始化测试"""

    @pytest.mark.asyncio
    async def test_create_with_llm_and_db(self):
        """创建 ChatAgent 需要 LLM provider 和 AsyncSession"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()

        agent = ChatAgent(llm_provider=llm, db=db)

        assert agent.llm is llm
        assert agent.db is db

    @pytest.mark.asyncio
    async def test_create_without_llm_raises(self):
        """缺少 LLM provider 应该抛出异常"""
        from backend.agents.chat_agent import ChatAgent

        with pytest.raises((TypeError, ValueError)):
            ChatAgent(llm_provider=None, db=make_mock_db())

    @pytest.mark.asyncio
    async def test_create_without_db_raises(self):
        """缺少数据库 session 应该抛出异常"""
        from backend.agents.chat_agent import ChatAgent

        with pytest.raises((TypeError, ValueError)):
            ChatAgent(llm_provider=make_mock_llm(), db=None)


class TestChatAgentSendMessage:
    """单轮消息发送测试"""

    @pytest.mark.asyncio
    async def test_send_simple_message_returns_response(self):
        """发送一条简单消息，应该返回聊天响应"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm("A 股市场当前处于震荡格局。")
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        result = await agent.send_message(
            user_id="test-user-1",
            message="当前 A 股市场走势如何？",
        )

        assert result is not None
        assert hasattr(result, "content")
        assert "A 股" in result.content
        assert hasattr(result, "conversation_id")

    @pytest.mark.asyncio
    async def test_send_message_calls_llm_chat(self):
        """发送消息应该调用 LLM 的 chat 方法"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        await agent.send_message(
            user_id="test-user-1",
            message="帮我分析一下 600519",
        )

        llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_system_prompt_contains_role(self):
        """系统提示词应该包含价值投资分析师角色设定"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        await agent.send_message(
            user_id="test-user-1",
            message="你好",
        )

        call_args = llm.chat.await_args
        messages = call_args[0][0]  # first positional arg
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "价值投资" in system_msg["content"] or "分析" in system_msg["content"]


class TestChatAgentMultiTurn:
    """多轮对话测试"""

    @pytest.mark.asyncio
    async def test_multi_turn_preserves_context(self):
        """多轮对话应该保留历史上下文"""
        from backend.agents.chat_agent import ChatAgent
        from backend.models.memory import Conversation

        llm = make_mock_llm("根据上一轮的分析，600519 当前估值合理。")
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        # 第一轮 — 创建新对话
        result1 = await agent.send_message(
            user_id="test-user-1",
            message="帮我看看 600519",
        )
        conv_id = result1.conversation_id

        # 第二轮 — 模拟加载已有对话
        # 构建一个模拟的 Conversation 对象用于 db.execute 返回
        existing_conv = MagicMock()
        existing_conv.messages = [
            {"role": "system", "content": "你是价值投资分析师..."},
            {"role": "user", "content": "帮我看看 600519"},
            {"role": "assistant", "content": "600519 是贵州茅台..."},
        ]

        # 重新创建 agent，但 db.execute 返回带历史消息的对话
        db2 = make_mock_db(conversation_for_load=existing_conv)
        llm2 = make_mock_llm("根据上一轮的分析，600519 当前估值合理。")
        agent2 = ChatAgent(llm_provider=llm2, db=db2)

        result2 = await agent2.send_message(
            user_id="test-user-1",
            message="它的估值合理吗？",
            conversation_id=conv_id,
        )

        # 验证 LLM 调用包含历史消息
        call_args = llm2.chat.await_args
        messages = call_args[0][0]
        # 应该包含 system + 历史的 user+assistant + 新的 user
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) >= 2, f"期望至少 2 条 user 消息，实际 {len(user_msgs)}"
        assert result2.conversation_id == conv_id

    @pytest.mark.asyncio
    async def test_new_conversation_when_no_id_provided(self):
        """不提供 conversation_id 时自动创建新对话"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        result1 = await agent.send_message(
            user_id="test-user-1",
            message="第一轮",
        )
        result2 = await agent.send_message(
            user_id="test-user-1",
            message="第二轮",
        )

        # 每次都应该有 conversation_id
        assert result1.conversation_id is not None
        assert result2.conversation_id is not None


class TestChatAgentStream:
    """流式响应测试"""

    @pytest.mark.asyncio
    async def test_stream_returns_async_iterator(self):
        """流式方法应该返回异步迭代器"""
        from backend.agents.chat_agent import ChatAgent

        async def mock_stream(messages):
            chunks = ["价值", "投资", "是", "一种", "长期", "策略"]
            for chunk in chunks:
                yield chunk + " "

        llm = make_mock_llm()
        llm.chat_stream = AsyncMock(return_value=mock_stream([{"role": "user", "content": "test"}]))
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        stream = await agent.send_message_stream(
            user_id="test-user-1",
            message="介绍价值投资",
        )

        # 应该是异步可迭代对象
        assert hasattr(stream, "__aiter__")

        chunks = []
        async for chunk in stream:
            chunks.append(chunk)

        assert len(chunks) > 0
        assert all(isinstance(c, str) for c in chunks)


class TestChatAgentMemoryInjection:
    """记忆注入测试"""

    @pytest.mark.asyncio
    async def test_memory_context_injected_when_enabled(self):
        """启用记忆注入时，系统提示词应该包含记忆上下文"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        # Mock MemoryRetriever.build_context
        with patch(
            "backend.agents.chat_agent.MemoryRetriever.build_context",
            new_callable=AsyncMock,
            return_value="用户偏好：偏好消费行业、PE<20",
        ):
            await agent.send_message(
                user_id="test-user-1",
                message="有什么好的投资机会？",
                inject_memory=True,
            )

        # 验证 LLM 调用中包含了记忆上下文
        call_args = llm.chat.await_args
        messages = call_args[0][0]
        system_msg = messages[0]
        content = system_msg["content"]
        assert "消费" in content

    @pytest.mark.asyncio
    async def test_memory_injection_disabled(self):
        """禁用记忆注入时，不应包含记忆上下文"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        with patch(
            "backend.agents.chat_agent.MemoryRetriever.build_context",
            new_callable=AsyncMock,
        ) as mock_build:
            await agent.send_message(
                user_id="test-user-1",
                message="你好",
                inject_memory=False,
            )
            mock_build.assert_not_called()


class TestChatAgentPersistence:
    """对话持久化测试"""

    @pytest.mark.asyncio
    async def test_conversation_saved_after_message(self):
        """发送消息后对话应保存到数据库"""
        from backend.agents.chat_agent import ChatAgent

        db = AsyncMock(spec=AsyncSession)
        llm = make_mock_llm()
        agent = ChatAgent(llm_provider=llm, db=db)

        await agent.send_message(
            user_id="test-user-1",
            message="测试消息",
        )

        # 验证有 commit 操作（保存对话）
        assert db.commit.called or db.flush.called

    @pytest.mark.asyncio
    async def test_get_history_returns_conversations(self):
        """获取历史记录应返回对话列表"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        history = await agent.get_history(user_id="test-user-1")

        assert isinstance(history, list)

    @pytest.mark.asyncio
    async def test_delete_conversation(self):
        """删除对话应该成功"""
        from backend.agents.chat_agent import ChatAgent

        llm = make_mock_llm()
        db = make_mock_db()
        agent = ChatAgent(llm_provider=llm, db=db)

        result = await agent.delete_conversation(conversation_id="conv-123")

        assert result is True or result is False  # bool 返回
