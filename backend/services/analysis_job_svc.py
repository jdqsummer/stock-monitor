# stock-monitor/backend/services/analysis_job_svc.py
import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from backend.agents.analysis_chain import create_analysis_chain
from backend.db.database import async_session_factory
from backend.llm.provider import is_llm_available
from backend.models.user import User
from backend.services.portfolio_svc import PortfolioService
from backend.services.reminder_svc import ReminderService
from backend.services.snapshot_svc import SnapshotService
from backend.services.watchlist_svc import WatchlistService

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped_llm_unavailable"

# 进程级全局并发上限：所有 job 的并发分析总数闸（与单 job 上限一致，取 10）。
# 16:00 多个自动分析 job 同时触发时，若无此闸，总并发 = 用户数 × 各自 analysis_concurrency，
# 会打爆 DSH 引擎（backend 提交并发必须 ≤ DSH max_sessions）。
_GLOBAL_CONCURRENCY = 10


class AnalysisJobService:
    """异步分析队列：提交 job → 逐只跑 9 步链 → 落库 B 表，状态内存跟踪。"""

    def __init__(
        self,
        per_stock_timeout: float = 120.0,
        chain=None,
        llm_available=None,
        session_factory=None,
    ):
        self._jobs: dict[str, dict] = {}
        self._timeout = per_stock_timeout
        self._chain = chain
        self._llm_available = llm_available or is_llm_available
        self._session_factory = session_factory or async_session_factory
        # I2 同股票 asyncio 锁（单进程防线）：同秒重复提交被串行化，
        # 与 session_id = code-date 的天然去重构成双防线
        self._code_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        # 两级信号量之进程级：限制所有 job 的并发分析总数，防 16:00 多 job 同时触发打爆 DSH。
        # job 级（per-job sem，见 _run）限制单 job 并发；进程级（本闸）限制全局总并发。
        self._global_sem = asyncio.Semaphore(_GLOBAL_CONCURRENCY)

    def create_job(self, user_id: str, codes: list[str], source: str) -> str:
        job_id = f"job_{uuid4().hex[:8]}"
        self._jobs[job_id] = {
            "job_id": job_id,
            "user_id": user_id,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "codes": {code: STATUS_PENDING for code in codes},
        }
        return job_id

    def submit(self, user_id: str, codes: list[str], source: str, model: str = "",
               concurrency: int | None = None,
               mode: str = "watchlist", modes: dict | None = None) -> str:
        job_id = self.create_job(user_id, codes, source)
        self._jobs[job_id]["model"] = model       # I6：每 job 的模型（前端模型下拉 → 全批次统一）
        self._jobs[job_id]["mode"] = mode
        self._jobs[job_id]["modes"] = modes or {}     # code → mode（混合批）
        if concurrency is not None:
            self._jobs[job_id]["concurrency"] = max(1, min(10, concurrency))
        asyncio.create_task(self._run(job_id))
        return job_id

    def get_status(self, job_id: str, user_id: str | None = None) -> dict | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if user_id is not None and job["user_id"] != user_id:
            return None
        codes = job["codes"]
        total = len(codes)
        return {
            "job_id": job_id,
            "source": job["source"],
            "total": total,
            "done": sum(1 for s in codes.values() if s == STATUS_DONE),
            "failed": sum(1 for s in codes.values() if s == STATUS_FAILED),
            "skipped": sum(1 for s in codes.values() if s == STATUS_SKIPPED),
            "running": sum(1 for s in codes.values() if s == STATUS_RUNNING),
            "results": dict(codes),
        }

    def get_active_job(self, user_id: str, source: str | None = None) -> dict | None:
        """该用户最近创建的进行中 job 的 status（切页/刷新后前端恢复进度用）。

        job 处于进行中 ⇔ 至少一个 code 仍是 pending/running（未全部终态）。
        全部终态或非该用户 → None。无 job_id 依赖，前端刷新后无需记住旧 job。
        source 非空时仅匹配该来源（如持仓页只恢复 portfolio job，不与自选股 job 抢）。
        """
        terminal = (STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED)
        active = [
            job for job in self._jobs.values()
            if job["user_id"] == user_id
            and (source is None or job.get("source") == source)
            and any(s not in terminal for s in job["codes"].values())
        ]
        if not active:
            return None
        latest = max(active, key=lambda j: j["created_at"])
        return self.get_status(latest["job_id"], user_id)

    async def _run(self, job_id: str):
        job = self._jobs[job_id]
        user_id = job["user_id"]
        codes = list(job["codes"].keys())
        default_mode = job.get("mode", "watchlist")
        async with self._session_factory() as session:
            try:
                items = await WatchlistService.list_items(session, user_id)
                positions = await PortfolioService.list_positions(session, user_id)
                positions_by_code = {p.stock_code: p for p in positions}
            finally:
                await session.close()
        by_code = {it.stock_code: it for it in items}
        concurrency = max(1, min(10, job.get("concurrency") or 3))
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(*(
            self._process_one(job_id, code, user_id, by_code.get(code),
                              positions_by_code.get(code),
                              job.get("modes", {}).get(code, default_mode), sem)
            for code in codes))

    def _timeout_for(self) -> float:
        """单次分析超时：DSH 开启时用 DSH_TIMEOUT_SECONDS（P2 实测五段 >8min，120s 会误降级），
        否则沿用现有 per_stock_timeout（OpenHarness 时代的 120s）。"""
        from backend.config import settings
        return settings.DSH_TIMEOUT_SECONDS if settings.DSH_ENABLED else self._timeout

    async def _lock_for(self, code: str) -> asyncio.Lock:
        """按股票代码取 asyncio 锁（惰性创建）——I2 同股票串行化。"""
        async with self._locks_guard:
            if code not in self._code_locks:
                self._code_locks[code] = asyncio.Lock()
            return self._code_locks[code]

    async def _safe_notify(self, user_id: str, fn, *args) -> None:
        """写系统消息（尽力而为）：失败只记日志，绝不改变分析状态流转。"""
        try:
            async with self._session_factory() as session:
                try:
                    await fn(session, user_id, *args)
                finally:
                    await session.close()
        except Exception as e:
            logger.warning(f"系统消息写入失败 user={user_id}: {e}")

    async def _process_one(self, job_id: str, code: str, user_id: str, item, position, mode: str,
                           sem: asyncio.Semaphore):
        job = self._jobs[job_id]
        # 两级闸，锁获取次序恒为 code lock → 进程级闸(_global_sem) → job 级闸(sem)：
        # - code lock：同 code 永不并发（I2 第二道防线），多个同 code job 撞车时锁等待者不占任何
        #   semaphore 槽位（避免饿死其他股票）。
        # - _global_sem：进程级总并发闸，防 16:00 多 job 同时触发时总并发 = 用户数 × concurrency 打爆 DSH。
        # - sem（per-job）：限制单 job 并发（submit 的 analysis_concurrency）。
        # 每任务只持一把 code 锁，锁获取次序全局一致，无嵌套循环等待 → 无死锁。
        lock = await self._lock_for(code)
        async with lock:
            async with self._global_sem:
                async with sem:
                    job["codes"][code] = STATUS_RUNNING
                    try:
                        if not self._llm_available():
                            job["codes"][code] = STATUS_SKIPPED
                            # 全局性错误：code/name 置空 → 同一天只写一条 api_config 消息，
                            # 避免 N 只股票各写一条刷屏（唯一索引按 user+category+code+date 去重）
                            await self._safe_notify(
                                user_id, ReminderService.notify_llm_unavailable, "", "")
                            return
                        api_keys = {}
                        async with self._session_factory() as session:
                            try:
                                user = await session.get(User, user_id)
                                cfg = (user.config or {}) if user else {}
                                api_keys = {k: cfg[k] for k in
                                            ("deepseek_api_key", "qwen_api_key", "kimi_api_key")
                                            if cfg.get(k)}
                            finally:
                                await session.close()
                        # create_analysis_chain 注入 LLM（has_real_llm=True → OpenHarness 走 LLM 定性路径）；
                        # 若用无参 AnalysisChain()（llm_provider=None），批量/自选分析只跑纯规则，缺定性/风险/清单
                        chain = self._chain or create_analysis_chain()
                        name = item.stock_name if item else ""
                        industry = item.industry if item else ""
                        model = job.get("model", "")          # 每 job 的模型（submit 传入，I6）
                        timeout = self._timeout_for()
                        # position 模式注入持仓上下文（仅 shares/cost_price/purchased_at 供分析；
                        # holding_value/holding_days 由展示层实时算，不在此注入）
                        position_context = None
                        if position is not None:
                            position_context = {
                                "shares": position.shares,
                                "cost_price": position.cost_price,
                                "purchased_at": position.purchased_at.isoformat() if position.purchased_at else None,
                            }
                        report = await asyncio.wait_for(
                            chain.analyze(code, stock_name=name, industry=industry,
                                          model=model, api_keys=api_keys,
                                          mode=mode, position_context=position_context),
                            timeout=timeout,
                        )
                        async with self._session_factory() as session:
                            try:
                                await SnapshotService.save_snapshot(session, user_id, report, source=job["source"])
                            finally:
                                await session.close()
                        await self._safe_notify(user_id, ReminderService.notify_analysis_outcome, report)
                        job["codes"][code] = STATUS_DONE
                    except Exception as e:
                        logger.error(f"分析失败 {code}: {e}")
                        job["codes"][code] = STATUS_FAILED
                        name = item.stock_name if item else ""
                        await self._safe_notify(user_id, ReminderService.notify_analysis_error, code, name, e)


analysis_job_service = AnalysisJobService()
