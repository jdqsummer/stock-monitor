import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import async_session_factory
from backend.memory.distillation import DistillationPipeline
from backend.memory.retrieval import MemoryRetriever

logger = logging.getLogger(__name__)


class MemoryService:
    """记忆服务编排层：检索 + 蒸馏 + 调度"""

    def __init__(self, llm_model: str = "deepseek-chat"):
        self.pipeline = DistillationPipeline(llm_model)

    async def retrieve_context(self, db: AsyncSession, user_id: str, query: str) -> str:
        """检索记忆上下文（供 Agent 注入）"""
        retriever = MemoryRetriever(db, user_id)
        return await retriever.build_context(query)

    def distill_async(self, user_id: str, conversation_text: str):
        """
        异步蒸馏（不阻塞主流程）。

        启动后台任务处理 L1/L2 蒸馏，Agent 响应不等待此任务完成。
        """
        async def _run():
            try:
                async with async_session_factory() as db:
                    await self.pipeline.distill_conversation(db, user_id, conversation_text)
                logger.info(f"异步蒸馏完成: user={user_id}")
            except Exception as e:
                logger.error(f"异步蒸馏失败: {e}")

        asyncio.create_task(_run())
        logger.info(f"异步蒸馏已提交: user={user_id}")

    async def update_L3_profile(self, user_id: str):
        """定时更新 L3 用户画像"""
        try:
            async with async_session_factory() as db:
                profile = await self.pipeline.build_L3_profile(db, user_id)
                logger.info(f"L3 画像更新完成: user={user_id}, len={len(profile)}")
        except Exception as e:
            logger.error(f"L3 画像更新失败: {e}")
