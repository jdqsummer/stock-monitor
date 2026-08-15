# stock-monitor/backend/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apscheduler.triggers.interval import IntervalTrigger

from backend.api import api_router
from backend.data.dsh_bridge import mcp as dsh_mcp
from backend.data.scheduler import TaskScheduler
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
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=30),
                      job_id="financials_refresh", name="财报数据刷新")
    scheduler.add_analysis_job(run_closing_tasks)           # 16:00 全局收盘任务

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
