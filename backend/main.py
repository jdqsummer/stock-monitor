# stock-monitor/backend/main.py
import sys
from pathlib import Path

# 防御性引导：确保 vendored openharness（仓库根 vendor/）在 sys.path 上，
# 使 harness_component 的 `import openharness.*` 在开发/非 Docker 环境同样可解析。
_VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import api_router
from backend.data.scheduler import TaskScheduler
from backend.services.refresh_svc import run_quote_refresh, run_recompute_analysis

from apscheduler.triggers.interval import IntervalTrigger


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = TaskScheduler()
    # 行情 30min 刷新（交易时段由 MarketCalendar 判断）；收盘重算 B
    scheduler.add_quote_refresh_job(run_quote_refresh, interval_minutes=30)
    scheduler.add_analysis_job(run_recompute_analysis)

    from backend.services.refresh_svc import run_financials_refresh
    scheduler.add_job(run_financials_refresh, IntervalTrigger(minutes=30),
                      job_id="financials_refresh", name="财报数据刷新")

    # 每用户自动分析 reconcile（start 前，确保 startup 时已注册）
    from backend.services.refresh_svc import collect_auto_analysis_users, run_user_auto_analysis
    from backend.db.database import async_session_factory

    async def _collect_users():
        async with async_session_factory() as session:
            try:
                return await collect_auto_analysis_users(session)
            finally:
                await session.close()

    await scheduler.sync_auto_analysis_jobs(_collect_users, run_user_auto_analysis)

    scheduler.start()
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


@app.get("/api/health")
async def health_check():
    return {"code": 0, "data": {"status": "ok"}, "message": "ok"}
