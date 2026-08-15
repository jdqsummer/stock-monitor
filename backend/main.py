# stock-monitor/backend/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import api_router
from backend.data.dsh_bridge import mcp as dsh_mcp
from backend.data.scheduler import TaskScheduler
from backend.services.refresh_svc import (
    collect_auto_analysis_users, collect_quote_refresh_users,
    run_user_auto_analysis, run_user_quote_refresh,
)

from apscheduler.triggers.interval import IntervalTrigger


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = TaskScheduler()
    app.state.scheduler = scheduler          # Task 4 配置保存触发 reconcile 用

    from backend.services.refresh_svc import run_financials_refresh
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=30),
                      job_id="financials_refresh", name="财报数据刷新")

    # 每用户行情刷新 + 自动分析 reconcile（start 前，确保 startup 时已注册）
    from backend.db.database import async_session_factory

    async def _collect_quote_users():
        async with async_session_factory() as session:
            try:
                return await collect_quote_refresh_users(session)
            finally:
                await session.close()

    async def _collect_users():
        async with async_session_factory() as session:
            try:
                return await collect_auto_analysis_users(session)
            finally:
                await session.close()

    await scheduler.sync_quote_refresh_jobs(_collect_quote_users, run_user_quote_refresh)
    await scheduler.sync_auto_analysis_jobs(_collect_users, run_user_auto_analysis)

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
