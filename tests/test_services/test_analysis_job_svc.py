import asyncio

import pytest

from backend.agents.analysis_chain import AnalysisReport
from backend.services.analysis_job_svc import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    AnalysisJobService,
)


@pytest.mark.asyncio
async def test_default_chain_uses_llm_aware_constructor(db_session, test_session_factory, monkeypatch):
    """默认 chain 必须用 create_analysis_chain（带 LLM），不能用无 LLM 的 AnalysisChain()

    AnalysisChain() 默认 llm_provider=None → AnalysisAgent.has_real_llm=False →
    走纯规则子链，moat_assessment/risk_factors/checklist_summary 全空（生产定性分析缺失的根因）。
    """
    from sqlalchemy import select

    from backend.models.stock import WatchlistItem
    from backend.services import analysis_job_svc as svc_mod

    calls = []

    def fake_create():
        calls.append(1)
        return FakeChain()

    monkeypatch.setattr(svc_mod, "create_analysis_chain", fake_create)

    db_session.add(WatchlistItem(user_id="u1", stock_code="600519", stock_name="贵州茅台", industry="白酒"))
    await db_session.commit()

    svc = AnalysisJobService(llm_available=lambda: True, session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    await svc._run(job_id)

    assert calls, "默认 chain 应通过 create_analysis_chain 构造（带 LLM），否则批量分析无定性结论"
    assert svc.get_status(job_id)["results"]["600519"] == STATUS_DONE
    rows = (await db_session.execute(select(WatchlistItem))).scalars().all()
    assert len(rows) == 1


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

    async def analyze(self, code, stock_name="", user_query="", industry="", model="", api_keys=None):
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
async def test_per_job_concurrency_param_controls_semaphore(db_session, test_session_factory):
    """submit(concurrency=1) → 串行；concurrency=3 → 不同股票并发 3"""
    from backend.services.analysis_job_svc import AnalysisJobService

    class ProbeChain:
        def __init__(self):
            self.active = 0
            self.max_active = 0
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return _report(code)

    probe = ProbeChain()
    svc = AnalysisJobService(chain=probe, llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858", "600036"], "manual")
    svc._jobs[job_id]["concurrency"] = 1
    await svc._run(job_id)
    assert probe.max_active == 1

    probe.max_active = 0
    job2 = svc.create_job("u1", ["600519", "000858", "600036"], "manual")
    svc._jobs[job2]["concurrency"] = 3
    await svc._run(job2)
    assert probe.max_active == 3


@pytest.mark.asyncio
async def test_concurrency_limited(db_session, test_session_factory):
    """semaphore=1 时串行：两任务总耗时 ≈ 2 × 单任务耗时"""

    class SlowChain:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def analyze(self, code, stock_name="", user_query="", industry="", model="", api_keys=None):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return _report(code)

    slow = SlowChain()
    svc = AnalysisJobService(chain=slow, llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    svc._jobs[job_id]["concurrency"] = 1
    await svc._run(job_id)
    assert slow.max_active == 1
    assert svc.get_status(job_id)["done"] == 2


@pytest.mark.asyncio
async def test_queued_codes_stay_pending_while_running(db_session, test_session_factory):
    """semaphore 未授予前，排队股票保持 pending，而非误标 running"""
    from backend.services.analysis_job_svc import STATUS_PENDING, STATUS_RUNNING

    class SlowChain:
        async def analyze(self, code, stock_name="", user_query="", industry="", model="", api_keys=None):
            await asyncio.sleep(0.2)
            return _report(code)

    svc = AnalysisJobService(chain=SlowChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    svc._jobs[job_id]["concurrency"] = 1
    task = asyncio.create_task(svc._run(job_id))
    await asyncio.sleep(0.05)  # 第一只正在跑，第二只应仍在排队

    status = svc.get_status(job_id)
    assert status["running"] == 1
    assert status["results"]["600519"] == STATUS_RUNNING
    assert status["results"]["000858"] == STATUS_PENDING  # 未被误标 running

    await task
    assert svc.get_status(job_id)["done"] == 2


@pytest.mark.asyncio
async def test_job_service_concurrent_same_code_serialized(db_session, test_session_factory):
    """同股票并发：asyncio 锁保证同秒重复提交被串行化（I2 第二道防线）。

    两个 job 同时对同一 code 发起分析（如定时刷新 + 手动触发撞车）→ _code_locks
    保证两次进入 chain.analyze 的时间窗口不重叠（跨 job 的 code 锁）。
    """
    from backend.services.analysis_job_svc import AnalysisJobService

    windows = []  # (code, start, end)

    class StubChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None):
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0.05)
            end = asyncio.get_event_loop().time()
            windows.append((code, start, end))
            return _report(code)

    svc = AnalysisJobService(chain=StubChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_a = svc.create_job("u1", ["600519"], "manual")
    job_b = svc.create_job("u1", ["600519"], "scheduled")
    await asyncio.gather(svc._run(job_a), svc._run(job_b))

    assert len(windows) == 2
    (c1, s1, e1), (c2, s2, e2) = windows
    assert c1 == c2 == "600519"
    # 串行化：第二次进入不早于第一次结束（两窗口不重叠）
    assert s2 >= e1


@pytest.mark.asyncio
async def test_different_codes_run_concurrently(db_session, test_session_factory):
    """不同 code 并发：锁按 code 隔离不误伤，两只不同股票可同时进入分析。

    同股票锁只串行化同一 code；不同 code 之间不应被锁挡住（信号量槽位仍可容纳两者）。
    回归防线：防止「先取锁后取信号量」改动误伤不同股票并发。
    """
    from backend.services.analysis_job_svc import AnalysisJobService

    class StubChain:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return _report(code)

    stub = StubChain()
    svc = AnalysisJobService(chain=stub, llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    await svc._run(job_id)

    assert stub.max_active == 2     # 不同 code 同时进入分析（锁不串行化不同股票）
    assert svc.get_status(job_id)["done"] == 2


@pytest.mark.asyncio
async def test_process_one_reads_model_from_job(db_session, test_session_factory):
    """I6：submit 的 model 存 job["model"]，_process_one 读并透传给 chain.analyze"""
    from backend.services.analysis_job_svc import AnalysisJobService

    seen = {}

    class ModelChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None):
            seen["model"] = model
            return _report(code)

    svc = AnalysisJobService(chain=ModelChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    svc._jobs[job_id]["model"] = "deepseek-v4-pro"   # submit 会写入；此处直接模拟
    await svc._run(job_id)

    assert seen.get("model") == "deepseek-v4-pro"
    assert svc.get_status(job_id)["results"]["600519"] == STATUS_DONE


# ── 切页/刷新后恢复：get_active_job ──


@pytest.mark.asyncio
async def test_get_active_job_returns_latest_running(db_session, test_session_factory):
    """有进行中 job（存在 pending/running）→ 返回该用户最近创建的一个的 status。

    前端切页/刷新后靠此恢复进度：旧 job 已完成应从候选剔除，避免恢复已结束的分析。
    """
    from backend.services.analysis_job_svc import STATUS_PENDING, STATUS_RUNNING

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    done_id = svc.create_job("u1", ["600519"], "manual")
    svc._jobs[done_id]["codes"]["600519"] = STATUS_DONE   # 已完成，应从候选剔除
    running_id = svc.create_job("u1", ["000858", "600036"], "manual")
    svc._jobs[running_id]["codes"]["000858"] = STATUS_RUNNING
    # 600036 保持 pending

    status = svc.get_active_job("u1")
    assert status is not None
    assert status["job_id"] == running_id
    assert status["total"] == 2
    assert status["done"] == 0
    assert status["running"] == 1


@pytest.mark.asyncio
async def test_get_active_job_none_when_all_terminal(db_session, test_session_factory):
    """全部终态（done/failed/skipped）→ 无进行中 job，返回 None。"""
    from backend.services.analysis_job_svc import STATUS_FAILED, STATUS_SKIPPED

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519", "000858"], "manual")
    svc._jobs[job_id]["codes"]["600519"] = STATUS_FAILED
    svc._jobs[job_id]["codes"]["000858"] = STATUS_SKIPPED

    assert svc.get_active_job("u1") is None


@pytest.mark.asyncio
async def test_get_active_job_user_isolation(db_session, test_session_factory):
    """用户隔离：A 的进行中 job 对 B 不可见（配合 API 端点的当前用户过滤）。"""
    from backend.services.analysis_job_svc import STATUS_RUNNING

    svc = AnalysisJobService(chain=FakeChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u1", ["600519"], "manual")
    svc._jobs[job_id]["codes"]["600519"] = STATUS_RUNNING

    assert svc.get_active_job("u2") is None


@pytest.mark.asyncio
async def test_process_one_passes_api_keys_from_user_config(db_session, test_session_factory):
    """_process_one 读 UserConfig key → chain.analyze(api_keys=...)"""
    from backend.models.stock import WatchlistItem
    from backend.models.user import User

    async with test_session_factory() as s:
        s.add(User(id="u_k", email="k@x.com", password_hash="x",
                   config={"deepseek_api_key": "sk-ds"}))
        s.add(WatchlistItem(user_id="u_k", stock_code="600519", stock_name="贵州茅台"))
        await s.commit()

    seen = {}
    class KeyChain:
        async def analyze(self, code, stock_name="", industry="", model="", api_keys=None):
            seen["api_keys"] = api_keys
            return _report(code)

    svc = AnalysisJobService(chain=KeyChain(), llm_available=lambda: True,
                             session_factory=test_session_factory)
    job_id = svc.create_job("u_k", ["600519"], "manual")
    await svc._run(job_id)
    assert seen["api_keys"] == {"deepseek_api_key": "sk-ds"}
