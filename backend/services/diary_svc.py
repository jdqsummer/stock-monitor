# stock-monitor/backend/services/diary_svc.py
"""投资笔记服务 — CRUD + 一键 AI 投资心理/行为分析

analyze：LLM json_chat 结构化提取 decisions/emotion_tags，生成 ai_feedback（对照投资框架：
扣非优先/安全边际/避免追涨杀跌），写回笔记字段，并异步蒸馏到 L1（作为小助手记忆源）。
"""
import json
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.llm.provider import get_llm
from backend.models.diary import Diary
from backend.services.memory_svc import MemoryService

logger = logging.getLogger(__name__)

DIARY_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["buy", "sell", "watch"]},
                    "stock": {"type": "string"},
                    "price": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["type"],
            },
        },
        "emotion_tags": {"type": "array", "items": {"type": "string"}},
        "ai_feedback": {"type": "string"},
    },
    "required": ["decisions", "emotion_tags", "ai_feedback"],
}

_ANALYZE_PROMPT = (
    "你是一名资深价值投资行为分析师。请分析以下投资笔记，提取买卖决策与情绪标签，"
    "并给出理性行为点评（对照投资框架：扣非优先/安全边际/避免追涨杀跌）。\n\n"
    "笔记内容：\n{content}"
)


class DiaryService:
    @staticmethod
    async def list_recent(db: AsyncSession, user_id: str, limit: int = 5) -> list[Diary]:
        result = await db.execute(
            select(Diary).where(Diary.user_id == user_id)
            .order_by(Diary.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    @staticmethod
    async def list_page(db: AsyncSession, user_id: str, offset: int = 0,
                        limit: int = 20) -> dict:
        total = (await db.execute(
            select(func.count()).select_from(Diary).where(Diary.user_id == user_id))
        ).scalar_one()
        rows = await db.execute(
            select(Diary).where(Diary.user_id == user_id)
            .order_by(Diary.created_at.desc()).offset(offset).limit(limit))
        items = [{
            "id": d.id, "content": d.content, "decisions": d.decisions,
            "emotion_tags": d.emotion_tags, "ai_feedback": d.ai_feedback,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in rows.scalars().all()]
        return {"total": total, "items": items}

    @staticmethod
    async def get(db: AsyncSession, user_id: str, diary_id: str) -> Diary | None:
        return (await db.execute(select(Diary).where(
            Diary.id == diary_id, Diary.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, user_id: str, title: str | None,
                     content: str, parent_folder_id: str | None = None) -> Diary:
        d = Diary(id=str(uuid.uuid4()), user_id=user_id, title=title,
                  content=content, parent_folder_id=parent_folder_id)
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d

    @staticmethod
    async def update(db: AsyncSession, user_id: str, diary_id: str, *,
                     title: str | None = None, content: str | None = None,
                     parent_folder_id: str | None = None) -> Diary | None:
        """更新笔记；显式传 None 的字段保持原值（None 语义=不修改）。"""
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return None
        if content is not None:
            d.content = content
        if title is not None:
            d.title = title
        if parent_folder_id is not None:
            d.parent_folder_id = parent_folder_id
        await db.commit()
        await db.refresh(d)
        return d

    @staticmethod
    async def delete(db: AsyncSession, user_id: str, diary_id: str) -> bool:
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            return False
        await db.delete(d)
        await db.commit()
        return True

    @staticmethod
    async def analyze(db: AsyncSession, user_id: str, diary_id: str) -> dict:
        """一键 AI 投资心理/行为分析：LLM 结构化提取 + 写回 + 异步蒸馏 L1。"""
        d = await DiaryService.get(db, user_id, diary_id)
        if d is None:
            raise ValueError("笔记不存在")

        llm = get_llm()
        resp = await llm.json_chat(
            [{"role": "user", "content": _ANALYZE_PROMPT.format(content=d.content[:3000])}],
            schema=DIARY_ANALYZE_SCHEMA,
        )
        decisions = resp.get("decisions", [])
        emotion_tags = resp.get("emotion_tags", [])
        ai_feedback = resp.get("ai_feedback", "")

        d.decisions = decisions
        d.emotion_tags = emotion_tags
        d.ai_feedback = ai_feedback
        await db.commit()

        # 异步蒸馏到 L1（作为小助手记忆源；失败非致命）
        try:
            MemoryService().distill_async(user_id, d.content)
        except Exception as e:
            logger.warning(f"笔记蒸馏失败（非致命）: {e}")

        return {"decisions": decisions, "emotion_tags": emotion_tags,
                "ai_feedback": ai_feedback, "id": diary_id}
