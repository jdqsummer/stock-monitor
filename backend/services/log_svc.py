# stock-monitor/backend/services/log_svc.py
"""系统日志服务：insert + 分页查询 + 多维筛选。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.system_log import SystemLog

logger = logging.getLogger(__name__)


class LogService:
    # === Insert ===

    @staticmethod
    async def insert(
        db: AsyncSession,
        *,
        level: str,
        source: str,
        message: str,
        stack_trace: str | None = None,
        user_id: str | None = None,
        email: str | None = None,
        path: str | None = None,
        method: str | None = None,
        status_code: int | None = None,
    ) -> SystemLog:
        """插入一条系统日志。失败仅 logger.warning，不抛（业务 logger 不能被日志服务拖死）。"""
        log = SystemLog(
            id=str(uuid.uuid4()),
            level=level[:20],
            source=(source or "")[:255],
            message=(message or "")[:8192],
            stack_trace=(stack_trace or None) and stack_trace[:65535],
            user_id=user_id,
            email=(email or None) and email[:255],
            path=(path or None) and path[:500],
            method=(method or None) and method[:10],
            status_code=status_code,
        )
        try:
            db.add(log)
            await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"system_log 写入失败: {e}")
            await db.rollback()
        return log

    # === Cleanup ===

    @staticmethod
    async def delete_older_than(db: AsyncSession, days: int) -> int:
        """删除超过保留期的日志（I3：防止 system_logs 无限增长）。

        created_at 落库为 naive UTC（SQLite CURRENT_TIMESTAMP），
        因此 cutoff 也用 naive UTC 比较。
        """
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        result = await db.execute(delete(SystemLog).where(SystemLog.created_at < cutoff))
        await db.commit()
        return result.rowcount or 0

    # === Query ===

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        *,
        levels: Sequence[str] | None = None,
        source: str | None = None,
        email: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[SystemLog], int]:
        """返回 (items, total)。筛选：level 多选 / source 模糊 / email 模糊 / 时间范围。"""
        where = []
        if levels:
            where.append(SystemLog.level.in_(list(levels)))
        if source:
            where.append(SystemLog.source.contains(source))
        if email:
            where.append(SystemLog.email.contains(email))
        if start:
            where.append(SystemLog.created_at >= start)
        if end:
            where.append(SystemLog.created_at <= end)

        stmt = select(SystemLog)
        count_stmt = select(func.count(SystemLog.id))
        if where:
            stmt = stmt.where(and_(*where))
            count_stmt = count_stmt.where(and_(*where))

        stmt = stmt.order_by(SystemLog.created_at.desc()).offset(offset).limit(limit)
        items = (await db.execute(stmt)).scalars().all()
        total = (await db.execute(count_stmt)).scalar_one() or 0
        return list(items), int(total)


async def cleanup_expired_logs() -> int:
    """定时任务入口：清理超过保留期的系统日志（独立 session，自建自关）。"""
    from backend.db.database import async_session_factory
    async with async_session_factory() as session:
        try:
            return await LogService.delete_older_than(session, settings.SYSTEM_LOG_RETENTION_DAYS)
        finally:
            await session.close()
