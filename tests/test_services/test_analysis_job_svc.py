import asyncio

import pytest

from backend.agents.analysis_chain import AnalysisReport
from backend.services.analysis_job_svc import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    AnalysisJobService,
)


def _report(code: str, name: str = "测试股", industry: str = "") -> AnalysisReport:
    return AnalysisReport(
        code=code, name=name, data_date="2026-08-12",
        annual_profit_low=10, annual_profit_high=15, profit_method="H1×2",
        pe_low=15, pe_high=25,
        swing_market_cap_low=150, swing_market_cap_high=375,
        swing_price_low=15, swing_price_high=37.5,
        current_market_cap=200, current_price=20,
        distance_pct=-5.0, signal="green", final_rating="🟢",
        signal_label="击球区", recommendation="可分批建仓",
        moat_assessment="护城河", risk_factors=["风险1"],
        profit_quality_ok=True, industry_category=industry,
    )


class FakeChain:
    def __init__(self, fail_codes: set[str] | None = None):
        self.fail_codes = fail_codes or set()

    async def analyze(self, code, stock_name="", user_query="", industry=""):
        if code in self.fail_codes:
            raise RuntimeError("boom")
        return _report(code, name=stock_name or "测试股", industry=industry or "")


@pytest.mark.asyncio
async def test_submit_and_status(db_session, test_session_factory):
    from sqlalchemy import select
    from backend.models.stock import AnalysisSnapshot, WatchlistItem

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台", industry="白酒"))
    db_session.add(WatchlistItem(user_id="u1", stock_code="000858", stock_name="五粮液", industry="白酒"))
    await db_session.commit()

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)

    status = svc.get_status(job_id)
    assert status["total"] == 2
    assert status["done"] == 2
    assert status["results"]["600519"] == STATUS_DONE

    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 2
    by_code = {r.stock_code: r for r in rows}
    assert by_code["600519"].moat_assessment == "护城河"
    assert by_code["600519"].industry_category == "白酒"
    assert by_code["600519"].analysis_source == "manual"


@pytest.mark.asyncio
async def test_single_failure_does_not_block(db_session, test_session_factory):
    from sqlalchemy import select
    from backend.models.stock import AnalysisSnapshot

    svc = AnalysisJobService(chain=FakeChain(fail_codes={"600519"}),
                             llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)

    status = svc.get_status(job_id)
    assert status["done"] == 1
    assert status["failed"] == 1
    assert status["results"]["600519"] == STATUS_FAILED
    assert status["results"]["000858"] == STATUS_DONE
    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 1  # 失败那只不落库


@pytest.mark.asyncio
async def test_llm_unavailable_skips(db_session, test_session_factory):
    from sqlalchemy import select
    from backend.models.stock import AnalysisSnapshot

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: False,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "scheduled")
    await svc._run(job_id)

    status = svc.get_status(job_id)
    assert status["results"]["600519"] == STATUS_SKIPPED
    rows = (await db_session.execute(select(AnalysisSnapshot))).scalars().all()
    assert len(rows) == 0  # 不污染 B 表


@pytest.mark.asyncio
async def test_concurrency_limited(db_session, test_session_factory):
    """semaphore=1 时串行：两任务总耗时 ≈ 2 × 单任务耗时"""

    class SlowChain:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def analyze(self, code, stock_name="", user_query="", industry=""):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return _report(code)

    slow = SlowChain()
    svc = AnalysisJobService(chain=slow, llm_available=lambda: True, max_concurrency=1,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)
    assert slow.max_active == 1
    assert svc.get_status(job_id)["done"] == 2


@pytest.mark.asyncio
async def test_queued_codes_stay_pending_while_running(db_session, test_session_factory):
    """semaphore 未授予前，排队股票保持 pending，而非误标 running"""
    from backend.services.analysis_job_svc import STATUS_PENDING, STATUS_RUNNING

    class SlowChain:
        async def analyze(self, code, stock_name="", user_query="", industry=""):
            await asyncio.sleep(0.2)
            return _report(code)

    svc = AnalysisJobService(chain=SlowChain(), llm_available=lambda: True,
                             max_concurrency=1, session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    task = asyncio.create_task(svc._run(job_id))
    await asyncio.sleep(0.05)  # 第一只正在跑，第二只应仍在排队

    status = svc.get_status(job_id)
    assert status["running"] == 1
    assert status["results"]["600519"] == STATUS_RUNNING
    assert status["results"]["000858"] == STATUS_PENDING  # 未被误标 running

    await task
    assert svc.get_status(job_id)["done"] == 2
