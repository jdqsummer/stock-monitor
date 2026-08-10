import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory import Conversation, Memory

logger = logging.getLogger(__name__)


class MemoryStore:
    """记忆存储层 — L0-L3 全部 CRUD"""

    # ── L0: 对话记录 ──

    @staticmethod
    async def save_conversation(
        db: AsyncSession,
        user_id: str,
        agent_type: str,
        messages: list[dict],
        summary: str = "",
    ) -> Conversation:
        conv = Conversation(
            user_id=user_id,
            agent_type=agent_type,
            messages=messages,
            summary=summary,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        logger.info(f"L0 对话已保存: {conv.id} (type={agent_type})")
        return conv

    @staticmethod
    async def get_conversations(
        db: AsyncSession,
        user_id: str,
        agent_type: str | None = None,
        limit: int = 20,
    ) -> list[Conversation]:
        stmt = select(Conversation).where(Conversation.user_id == user_id)
        if agent_type:
            stmt = stmt.where(Conversation.agent_type == agent_type)
        stmt = stmt.order_by(desc(Conversation.created_at)).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── L1/L2/L3: 记忆条目 ──

    @staticmethod
    async def save_memory(
        db: AsyncSession,
        user_id: str,
        level: str,
        category: str,
        content: str,
        source: str = "",
        confidence: float = 1.0,
    ) -> Memory:
        memory = Memory(
            user_id=user_id,
            level=level,
            category=category,
            content=content,
            source=source,
            confidence=confidence,
        )
        db.add(memory)
        await db.commit()
        await db.refresh(memory)
        logger.info(f"[{level}] 记忆已保存: {memory.id} (category={category})")
        return memory

    @staticmethod
    async def get_memories(
        db: AsyncSession,
        user_id: str,
        level: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        stmt = select(Memory).where(Memory.user_id == user_id)
        if level:
            stmt = stmt.where(Memory.level == level)
        if category:
            stmt = stmt.where(Memory.category == category)
        stmt = stmt.order_by(desc(Memory.confidence), desc(Memory.updated_at)).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_memory(
        db: AsyncSession,
        memory_id: str,
        content: str | None = None,
        confidence: float | None = None,
    ) -> Memory | None:
        result = await db.execute(select(Memory).where(Memory.id == memory_id))
        memory = result.scalar_one_or_none()
        if not memory:
            return None
        if content is not None:
            memory.content = content
        if confidence is not None:
            memory.confidence = confidence
        memory.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(memory)
        return memory

    @staticmethod
    async def upsert_memory_by_category(
        db: AsyncSession,
        user_id: str,
        level: str,
        category: str,
        content: str,
        source: str = "",
        confidence: float = 1.0,
    ) -> Memory:
        existing = await MemoryStore.get_memories(db, user_id, level, category, limit=1)
        if existing:
            return await MemoryStore.update_memory(db, existing[0].id, content, confidence)
        return await MemoryStore.save_memory(db, user_id, level, category, content, source, confidence)

    @staticmethod
    async def delete_memory(db: AsyncSession, memory_id: str) -> bool:
        result = await db.execute(select(Memory).where(Memory.id == memory_id))
        memory = result.scalar_one_or_none()
        if memory:
            await db.delete(memory)
            await db.commit()
            return True
        return False
