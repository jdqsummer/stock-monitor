# stock-monitor/backend/agents/chat_agent.py
"""Chat Agent — SSE 流式对话 + 记忆检索注入 + 多轮对话

提供与用户进行多轮投资对话的 AI Agent。
整合记忆系统，自动注入用户投资画像和偏好到对话上下文中。
支持流式（SSE）和非流式两种响应模式。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.llm.provider import LLMProvider
from backend.memory.retrieval import MemoryRetriever
from backend.memory.store import MemoryStore
from backend.models.memory import Conversation

logger = logging.getLogger(__name__)


# ── 数据结构 ──

@dataclass
class ChatResponse:
    """单轮聊天响应"""
    content: str
    conversation_id: str
    model: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ── 系统提示词 ──

CHAT_SYSTEM_PROMPT = """你是一个资深的 A 股价值投资分析师，拥有 15 年投资经验。

你的投资理念基于：
- 价值投资框架：寻找好价格下的好公司
- 安全边际原则：只有当价格远低于内在价值时才买入
- 长期持有：关注企业的长期竞争力，而非短期市场波动
- 保守估值：使用扣非净利润，避免过度乐观的年化假设

在回答用户问题时：
1. 保持理性、客观，不追逐市场热点
2. 引用具体数据和逻辑推理
3. 当用户询问个股时，从利润质量、估值水平、安全边际三个维度分析
4. 如果信息不足，坦诚指出并建议用户补充
5. 永远不提供买卖建议，只做分析"""


# ── Chat Agent ──

class ChatAgent:
    """
    聊天 Agent — 整合记忆检索的对话引擎。

    使用方式：
        agent = ChatAgent(llm_provider=llm, db=session)
        resp = await agent.send_message(user_id="u1", message="分析 600519")
        print(resp.content)

        # 流式
        async for chunk in await agent.send_message_stream(user_id="u1", message="..."):
            print(chunk, end="")
    """

    def __init__(self, llm_provider: LLMProvider, db: AsyncSession):
        if llm_provider is None:
            raise ValueError("llm_provider 不能为 None")
        if db is None:
            raise ValueError("db 不能为 None")

        self.llm = llm_provider
        self.db = db

    # ── 公共 API ──

    async def send_message(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        inject_memory: bool = True,
    ) -> ChatResponse:
        """
        发送消息并获取非流式响应。

        Args:
            user_id: 用户 ID
            message: 用户消息
            conversation_id: 对话 ID（None 则创建新对话）
            inject_memory: 是否注入记忆上下文

        Returns:
            ChatResponse（content + conversation_id）
        """
        # 1. 加载或创建对话
        messages = await self._load_conversation(user_id, conversation_id, message)

        # 2. 注入记忆上下文
        if inject_memory:
            await self._inject_memory_context(user_id, messages)

        # 3. 调用 LLM
        resp = await self.llm.chat(messages)

        # 4. 保存对话
        conv_id = await self._save_conversation(
            user_id=user_id,
            messages=messages,
            assistant_content=resp.content,
            conversation_id=conversation_id,
        )

        return ChatResponse(
            content=resp.content,
            conversation_id=conv_id,
            model=resp.model,
        )

    async def send_message_stream(
        self,
        user_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        inject_memory: bool = True,
    ) -> AsyncIterator[str]:
        """
        发送消息并获取流式响应。

        Args:
            user_id: 用户 ID
            message: 用户消息
            conversation_id: 对话 ID（None 则创建新对话）
            inject_memory: 是否注入记忆上下文

        Returns:
            异步迭代器，逐块产出文本
        """
        # 1. 构建消息
        messages = await self._load_conversation(user_id, conversation_id, message)

        # 2. 注入记忆上下文
        if inject_memory:
            await self._inject_memory_context(user_id, messages)

        # 3. 调用 LLM 流式接口
        full_content = []

        async def _stream():
            nonlocal full_content
            stream = await self.llm.chat_stream(messages)
            async for chunk in stream:
                # chunk 可能是 str 或 LLMResponse-like object
                text = chunk if isinstance(chunk, str) else getattr(chunk, "content", str(chunk))
                full_content.append(text)
                yield text

            # 保存对话
            conv_id = await self._save_conversation(
                user_id=user_id,
                messages=messages,
                assistant_content="".join(full_content),
                conversation_id=conversation_id,
            )

        return _stream()

    async def get_history(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        获取用户的对话历史。

        Args:
            user_id: 用户 ID
            limit: 最大返回数量

        Returns:
            对话列表，每个对话包含 id, agent_type, messages, summary, created_at
        """
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        conversations = result.scalars().all()

        return [
            {
                "id": c.id,
                "agent_type": c.agent_type,
                "messages": c.messages,
                "summary": c.summary,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in conversations
        ]

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        删除指定对话。

        Args:
            conversation_id: 对话 ID

        Returns:
            是否成功删除
        """
        result = await self.db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            await self.db.delete(conv)
            await self.db.commit()
            return True
        return False

    # ── 内部方法 ──

    async def _load_conversation(
        self,
        user_id: str,
        conversation_id: Optional[str],
        new_message: str,
    ) -> list[dict]:
        """加载对话历史并追加新消息"""
        messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]

        if conversation_id:
            # 加载已有对话
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = result.scalar_one_or_none()
            if conv:
                # 追加历史消息（不含 system prompt）
                for msg in conv.messages:
                    if msg.get("role") != "system":
                        messages.append(msg)

        # 追加当前用户消息
        messages.append({"role": "user", "content": new_message})
        return messages

    async def _inject_memory_context(self, user_id: str, messages: list[dict]) -> None:
        """将记忆上下文注入到系统提示词中"""
        try:
            retriever = MemoryRetriever(self.db, user_id)
            ctx = await retriever.build_context(messages[-1]["content"])

            if ctx and messages:
                # 追加到系统提示词
                for i, msg in enumerate(messages):
                    if msg["role"] == "system":
                        messages[i]["content"] = msg["content"] + "\n\n" + ctx
                        break
        except Exception as e:
            logger.warning(f"记忆注入失败（非致命）: {e}")

    async def _save_conversation(
        self,
        user_id: str,
        messages: list[dict],
        assistant_content: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        """保存对话到数据库，返回 conversation_id"""
        # 添加 assistant 消息
        full_messages = list(messages) + [{"role": "assistant", "content": assistant_content}]

        if conversation_id:
            # 更新已有对话
            result = await self.db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = result.scalar_one_or_none()
            if conv:
                conv.messages = full_messages
                conv.summary = self._generate_summary(full_messages)
                await self.db.commit()
                return conversation_id

        # 创建新对话
        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            agent_type="chat",
            messages=full_messages,
            summary=self._generate_summary(full_messages),
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv.id

    def _generate_summary(self, messages: list[dict]) -> str:
        """从消息列表生成简短摘要"""
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        if user_msgs:
            first = user_msgs[0]
            return first[:100] if len(first) > 100 else first
        return ""
