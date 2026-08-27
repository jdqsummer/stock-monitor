# stock-monitor/backend/api/admin.py
"""管理后台：用户列表 / 系统日志 / 客户端日志上报。全部走 require_admin 鉴权。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_db, require_admin
from backend.config import settings
from backend.models.user import User
from backend.schemas.admin import (
    AdminUserInfo,
    ClientLogReport,
    PaginatedLogs,
    SystemLogEntry,
)
from backend.schemas.common import ApiResponse
from backend.services.log_svc import LogService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["管理后台"])


def _iso_utc(dt: datetime) -> str:
    """SQLite 存 naive UTC，补时区后序列化为 ISO（前端 dayjs 按本地时区展示，消除 8h 偏移）。

    空值返回 ""（与 str(None)="None" 不同，避免前端展示 None）。
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("/users", response_model=ApiResponse[list[AdminUserInfo]])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """全部用户列表（管理员视图，附 is_admin 标记）。"""
    rows = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    items = [
        AdminUserInfo(
            id=u.id,
            email=u.email,
            email_verified=u.email_verified,
            created_at=_iso_utc(u.created_at),
            last_login_at=_iso_utc(u.last_login_at) if u.last_login_at else None,
            is_admin=u.email.lower() == settings.ADMIN_EMAIL.lower(),
        )
        for u in rows
    ]
    return ApiResponse(data=items)


@router.get("/logs", response_model=ApiResponse[PaginatedLogs])
async def list_logs(
    levels: str | None = Query(default=None, description="逗号分隔: debug,info,warning,error,critical"),
    source: str | None = None,
    email: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """分页查询系统日志（按 created_at 倒序）。"""
    parsed_levels = [s.strip() for s in levels.split(",") if s.strip()] if levels else None
    items, total = await LogService.list_logs(
        db,
        levels=parsed_levels,
        source=source,
        email=email,
        start=start,
        end=end,
        offset=offset,
        limit=limit,
    )
    return ApiResponse(
        data=PaginatedLogs(
            items=[
                SystemLogEntry(
                    id=l.id,
                    level=l.level,
                    source=l.source,
                    message=l.message,
                    stack_trace=l.stack_trace,
                    user_id=l.user_id,
                    email=l.email,
                    path=l.path,
                    method=l.method,
                    status_code=l.status_code,
                    created_at=_iso_utc(l.created_at),
                )
                for l in items
            ],
            total=total,
            offset=offset,
            limit=limit,
        )
    )


@router.post("/logs", response_model=ApiResponse)
async def report_client_log(
    payload: ClientLogReport,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """前端 console 重写后上报的日志。鉴权收紧到管理员：避免任意用户刷入日志污染。

    注意：axios 拦截器 + consoleInterceptor 对所有已登录用户都会触发上报，
    非管理员请求在此被 403 拦截（前端 .catch 静默）。即只有管理员会话内的
    前端错误能入库；后端 5xx 错误不受影响，对所有用户的请求都会落库。
    """
    await LogService.insert(
        db,
        level=payload.level,
        source=payload.source or "frontend.console",
        message=payload.message,
        stack_trace=payload.stack_trace,
        user_id=admin.id,
        email=admin.email,
        path=payload.path or request.url.path,
        method=payload.method,
        status_code=payload.status_code,
    )
    return ApiResponse(message="ok")
