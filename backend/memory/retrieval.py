import logging
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession

from backend.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# 检索限制
LIMITS = {"L1": 20, "L2": 10, "L3": 1}


class MemoryRetriever:
    """
    分层记忆检索器。

    检索策略：
    - L1（投资偏好）：关键词 + category 精确匹配
    - L2（场景知识）：语义相似度排序（简化：difflib 字符串相似度）
    - L3（投资画像）：直接返回用户画像全文
    """

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    async def retrieve(
        self,
        query: str,
        levels: list[str] | None = None,
    ) -> dict[str, list[dict]]:
        if levels is None:
            levels = ["L1", "L2", "L3"]

        result = {}

        for level in levels:
            limit = LIMITS.get(level, 20)
            memories = await MemoryStore.get_memories(
                self.db, self.user_id, level=level, limit=100
            )

            if level == "L1":
                scored = [(m, self._keyword_score(m, query)) for m in memories]
                scored.sort(key=lambda x: x[1], reverse=True)
                result["L1"] = [self._to_dict(m) for m, _ in scored[:limit]]

            elif level == "L2":
                scored = [(m, self._similarity_score(m.content, query)) for m in memories]
                scored.sort(key=lambda x: x[1], reverse=True)
                result["L2"] = [self._to_dict(m) for m, _ in scored[:limit]]

            elif level == "L3":
                result["L3"] = [self._to_dict(m) for m in memories[:limit]]

        return result

    async def build_context(self, query: str) -> str:
        """构建用于注入 Agent prompt 的记忆上下文"""
        memories = await self.retrieve(query)
        context_parts = []

        if memories.get("L3"):
            context_parts.append("## 用户投资画像\n" + "\n".join(
                m["content"] for m in memories["L3"]
            ))

        if memories.get("L2"):
            context_parts.append("## 相关策略知识\n" + "\n".join(
                f"- {m['content']}" for m in memories["L2"][:5]
            ))

        if memories.get("L1"):
            context_parts.append("## 投资偏好\n" + "\n".join(
                f"- [{m['category']}] {m['content']}" for m in memories["L1"][:10]
            ))

        return "\n\n".join(context_parts) if context_parts else ""

    # ── 内部方法 ──

    def _keyword_score(self, memory, query: str) -> float:
        score = 0.0
        if memory.category and any(kw in query for kw in memory.category.split()):
            score += 0.5
        content_words = set(memory.content.lower().split())
        query_words = set(query.lower().split())
        overlap = content_words & query_words
        if query_words:
            score += len(overlap) / len(query_words) * 0.5
        return score * (memory.confidence or 1.0)

    def _similarity_score(self, text1: str, text2: str) -> float:
        return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

    def _to_dict(self, memory) -> dict:
        return {
            "id": memory.id,
            "level": memory.level,
            "category": memory.category,
            "content": memory.content,
            "confidence": memory.confidence,
            "updated_at": str(memory.updated_at) if memory.updated_at else None,
        }
