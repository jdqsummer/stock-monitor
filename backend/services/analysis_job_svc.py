# stock-monitor/backend/services/analysis_job_svc.py
import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from backend.agents.analysis_chain import create_analysis_chain
from backend.db.database import async_session_factory
from backend.llm.provider import is_llm_available
from backend.services.snapshot_svc import SnapshotService
from backend.services.watchlist_svc import WatchlistService

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped_llm_unavailable"


class AnalysisJobService:
    """异步分析队列：提交 job → 逐只跑 9 步链 → 落库 B 表，状态内存跟踪。"""

    def __init__(
        self,
        max_concurrency: int = 3,
        per_stock_timeout: float = 120.0,
        chain=None,
        llm_available=None,
        session_factory=None,
    ):
        self._jobs: dict[str, dict] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = per_stock_timeout
        self._chain = chain
        self._llm_available = llm_available or is_llm_available
        self._session_factory = session_factory or async_session_factory
        # I2 同股票 asyncio 锁（单进程防线）：同秒重复提交被串行化，
        # 与 session_id = code-date 的天然去重构成双防线
        self._code_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

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

    def submit(self, user_id: str, codes: list[str], source: str, model: str = "") -> str:
        job_id = self.create_job(user_id, codes, source)
        self._jobs[job_id]["model"] = model       # I6：每 job 的模型（前端模型下拉 → 全批次统一）
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

    async def _run(self, job_id: str):
        job = self._jobs[job_id]
        user_id = job["user_id"]
        codes = list(job["codes"].keys())
        async with self._session_factory() as session:
            try:
                items = await WatchlistService.list_items(session, user_id)
            finally:
                await session.close()
        by_code = {it.stock_code: it for it in items}
        await asyncio.gather(
            *(self._process_one(job_id, code, user_id, by_code.get(code)) for code in codes)
        )

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

    async def _process_one(self, job_id: str, code: str, user_id: str, item):
        job = self._jobs[job_id]
        # 先取同股票锁、后取信号量（Important #2）：多个同 code job 撞车时，锁等待者不再占
        # semaphore 槽位（避免饿死其他股票）；同 code 永不并发（I2 第二道防线仍生效）。
        # 每任务只持一把 code 锁，锁获取次序恒为 code lock → semaphore，无嵌套循环等待 → 无死锁。
        lock = await self._lock_for(code)
        async with lock:
            async with self._semaphore:
                job["codes"][code] = STATUS_RUNNING
                try:
                    if not self._llm_available():
                        job["codes"][code] = STATUS_SKIPPED
                        return
                    # create_analysis_chain 注入 LLM（has_real_llm=True → OpenHarness 走 LLM 定性路径）；
                    # 若用无参 AnalysisChain()（llm_provider=None），批量/自选分析只跑纯规则，缺定性/风险/清单
                    chain = self._chain or create_analysis_chain()
                    name = item.stock_name if item else ""
                    industry = item.industry if item else ""
                    model = job.get("model", "")          # 每 job 的模型（submit 传入，I6）
                    timeout = self._timeout_for()
                    report = await asyncio.wait_for(
                        chain.analyze(code, stock_name=name, industry=industry, model=model),
                        timeout=timeout,
                    )
                    async with self._session_factory() as session:
                        try:
                            await SnapshotService.save_snapshot(session, user_id, report, source=job["source"])
                        finally:
                            await session.close()
                    job["codes"][code] = STATUS_DONE
                except Exception as e:
                    logger.error(f"分析失败 {code}: {e}")
                    job["codes"][code] = STATUS_FAILED


analysis_job_service = AnalysisJobService()
