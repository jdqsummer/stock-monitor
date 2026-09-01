# stock-monitor/backend/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.api import api_router
from backend.data.dsh_bridge import mcp as dsh_mcp
from backend.data.scheduler import TaskScheduler
from backend.services.log_handler import install as install_log_handler
from backend.services.refresh_svc import (
    collect_auto_analysis_users, collect_quote_refresh_users,
    run_recompute_analysis, run_reminder_checks,
    run_user_auto_analysis, run_user_quote_refresh,
)


async def run_closing_tasks() -> dict:
    """16:00 全局：收盘重算 B 表 + 击球区提醒检测"""
    recomputed = await run_recompute_analysis()
    reminders = await run_reminder_checks()
    return {"recomputed": recomputed, "reminders": reminders}


async def _reconcile_quote_and_auto(app):
    """启动/保存配置后对齐每用户行情刷新 + 自动分析 job"""
    scheduler = app.state.scheduler
    from backend.db.database import async_session_factory
    async with async_session_factory() as session:
        try:
            quote_users = await collect_quote_refresh_users(session)
            auto_users = await collect_auto_analysis_users(session)
        finally:
            await session.close()

    # sync_*_jobs 会 `await collect_func()`，故 collector 必须是 async 函数，
    # 此处闭包直接返回已采集列表（数据已在上面单次 session 内取齐）。
    async def _collect_quote_users():
        return quote_users

    async def _collect_auto_users():
        return auto_users

    await scheduler.sync_quote_refresh_jobs(_collect_quote_users, run_user_quote_refresh)
    await scheduler.sync_auto_analysis_jobs(_collect_auto_users, run_user_auto_analysis)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = TaskScheduler()
    app.state.scheduler = scheduler          # Task 4 配置保存触发 reconcile 用
    app.state.reconcile_all = _reconcile_quote_and_auto     # config 保存触发

    from backend.services.refresh_svc import run_financials_refresh
    # 修复 2（P0-2, 2026-09-01）：财报刷新频率 30min → 5min，减少财报发布高峰期滞后；
    # 范围由 collect_all_relevant_codes 扩展为自选∪持仓∪7天内分析过（见 refresh_svc）。
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=5),
                      job_id="financials_refresh", name="财报数据刷新")
    scheduler.add_analysis_job(run_closing_tasks)           # 16:00 全局收盘任务

    # 系统日志保留策略（I3）：每日 03:23 清理超过保留期的日志，防 system_logs 无限增长
    from backend.services.log_svc import cleanup_expired_logs
    scheduler.add_job(cleanup_expired_logs, CronTrigger(hour=3, minute=23),
                      job_id="system_log_cleanup", name="系统日志清理")

    # 一次性迁移：旧版平铺根目录的笔记图片 → 按用户子目录（幂等，见 diary_svc）
    from backend.db.database import async_session_factory
    from backend.services.diary_svc import migrate_legacy_diary_images
    async with async_session_factory() as session:
        try:
            await migrate_legacy_diary_images(session)
        finally:
            await session.close()

    # 管理后台：全局 logger → system_logs 自动入库
    install_log_handler()

    await _reconcile_quote_and_auto(app)
    scheduler.start()
    # DataBridge MCP session manager（streamable-http 辅助通道）生命周期随 app 启停。
    # 必须先于 yield 进入，否则 /mcp/investdata 端点报「Task group is not initialized」。
    async with dsh_mcp.session_manager.run():
        yield
    scheduler.shutdown()


app = FastAPI(
    title="股票监控系统",
    description="AI 企业价值与安全边际分析平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# DataBridge MCP mount（跨容器 streamable-http 辅助通道；DSH invest-data-mcp 连
# http://backend:8000/mcp/investdata，见 .dsh/agent-presets/value-investor/agent.cordis.yml）。
# FastMCP 默认 streamable_http_path='/mcp'，置 '/' 使端点恰为 /mcp/investdata
# （否则会变成 /mcp/investdata/mcp）。session manager 生命周期在 lifespan 内随 app 启停。
dsh_mcp.settings.streamable_http_path = "/"
app.mount("/mcp/investdata", dsh_mcp.streamable_http_app())


@app.get("/api/health")
async def health_check():
    return {"code": 0, "data": {"status": "ok"}, "message": "ok"}


# ── 全局异常处理：5xx 入 system_logs，但响应字段保持 FastAPI 默认契约（{"detail": ...}） ──

import logging as _logging
_app_logger = _logging.getLogger("backend.main")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """保留 FastAPI 默认响应形状 {"detail": ...}（业务测试与客户端都依赖该契约）；
    仅在 status >= 500 时额外走 logger.critical 落库。
    """
    if exc.status_code >= 500:
        _app_logger.critical(
            f"HTTP {exc.status_code} {request.method} {request.url.path}: {exc.detail}",
            extra={"path": request.url.path, "method": request.method, "status_code": exc.status_code},
            exc_info=(type(exc), exc, exc.__traceback__),  # I1: 传栈，DbLogHandler 据此填 stack_trace 列
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """未捕获异常 → critical 落库 + 500 响应（FastAPI 默认 detail 形状）。"""
    _app_logger.critical(
        f"Unhandled {type(exc).__name__} {request.method} {request.url.path}: {exc}",
        extra={"path": request.url.path, "method": request.method, "status_code": 500},
        exc_info=(type(exc), exc, exc.__traceback__),  # I1: 传栈，DbLogHandler 据此填 stack_trace 列
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
    )
