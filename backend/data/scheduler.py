# stock-monitor/backend/data/scheduler.py
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.data.market_calendar import MarketCalendar

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    定时任务调度器。

    管理数据刷新、分析更新等周期性任务。
    任务只在交易时段执行（通过 MarketCalendar 检查）。
    """

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._jobs = {}

    def start(self):
        self._scheduler.start()
        logger.info("任务调度器已启动")

    def shutdown(self):
        self._scheduler.shutdown(wait=False)
        logger.info("任务调度器已关闭")

    def add_quote_refresh_job(self, func, interval_minutes: int = 5):
        """添加行情刷新任务（交易时段）"""
        job = self._scheduler.add_job(
            func,
            IntervalTrigger(minutes=interval_minutes),
            id="quote_refresh",
            name="行情数据刷新",
            replace_existing=True,
        )
        self._jobs["quote_refresh"] = job
        logger.info(f"行情刷新任务已注册，间隔 {interval_minutes}min")

    def add_analysis_job(self, func, afternoon_time: str = "16:00"):
        """添加收盘任务（16:00 全局：重算 B 表 + 提醒检测）。早盘任务已移除。"""
        hour_a, minute_a = afternoon_time.split(":")
        job_a = self._scheduler.add_job(
            func,
            CronTrigger(hour=int(hour_a), minute=int(minute_a), day_of_week="mon-fri"),
            id="analysis_afternoon",
            name="收盘任务",
            replace_existing=True,
        )
        self._jobs["analysis_afternoon"] = job_a

    def add_job(self, func, trigger, job_id: str, name: str = ""):
        """通用任务注册"""
        job = self._scheduler.add_job(
            func,
            trigger,
            id=job_id,
            name=name,
            replace_existing=True,
        )
        self._jobs[job_id] = job
        return job

    def get_jobs_status(self) -> list[dict]:
        """获取所有任务状态"""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
            }
            for job in self._scheduler.get_jobs()
        ]

    async def sync_auto_analysis_jobs(self, collect_func, run_func):
        """按每用户 enabled + 时间 reconcile 定时分析 job（移除过期、新增/更新）"""
        current = await collect_func()
        wanted = {f"auto_{user_id}": time for user_id, time in current}

        # 移除已关闭用户的 job
        for job_id in list(self._jobs.keys()):
            if job_id.startswith("auto_") and job_id not in wanted:
                self._scheduler.remove_job(job_id)
                self._jobs.pop(job_id, None)

        # 新增/更新时间变化的 job
        for job_id, time_str in wanted.items():
            try:
                hour, minute = time_str.split(":")
                existing = self._jobs.get(job_id)
                next_run = existing.next_run_time if existing else None
                existing_cron = (next_run.hour, next_run.minute) if next_run else None
                if existing_cron == (int(hour), int(minute)):
                    continue
                if existing:
                    self._scheduler.remove_job(job_id)
                user_id = job_id[len("auto_"):]
                job = self._scheduler.add_job(
                    run_func,
                    CronTrigger(hour=int(hour), minute=int(minute), day_of_week="mon-fri"),
                    id=job_id,
                    name=f"自选股自动分析 {user_id}",
                    args=[user_id],
                    replace_existing=True,
                )
                self._jobs[job_id] = job
            except (ValueError, IndexError) as e:
                # 坏时间格式（如 "bad" / "25:00"）只跳过该用户，不阻断整批。
                # 若该用户此前有有效 job，需一并移除 scheduler 中残留的幽灵 job；
                # 但仅当 job 仍存在于 scheduler 时才调用 remove_job（"25:00" 场景下
                # remove_job 已在 try 内执行过，重复调用会抛 JobLookupError）。
                logger.warning(f"跳过用户 {job_id} 的无效分析时间: {e}")
                if job_id in self._jobs:
                    if any(j.id == job_id for j in self._scheduler.get_jobs()):
                        self._scheduler.remove_job(job_id)
                    self._jobs.pop(job_id, None)
                continue

    async def sync_quote_refresh_jobs(self, collect_func, run_func):
        """按每用户间隔 reconcile 行情刷新 job（IntervalTrigger）"""
        current = await collect_func()
        wanted = {f"quote_{user_id}": minutes for user_id, minutes in current}

        for job_id in list(self._jobs.keys()):
            if job_id.startswith("quote_") and job_id not in wanted:
                self._scheduler.remove_job(job_id)
                self._jobs.pop(job_id, None)

        for job_id, minutes in wanted.items():
            try:
                minutes = int(minutes)
                if minutes < 5 or minutes > 1440:
                    raise ValueError(f"间隔需在 [5, 1440] 分钟: {minutes}")
                user_id = job_id[len("quote_"):]
                job = self._scheduler.add_job(
                    run_func,
                    IntervalTrigger(minutes=minutes),
                    id=job_id,
                    name=f"行情刷新 {user_id}",
                    args=[user_id],
                    replace_existing=True,
                )
                self._jobs[job_id] = job
            except (ValueError, TypeError) as e:
                # 坏间隔（非数字 / None / <5 / >1440）只跳过该用户，不阻断整批。
                # 若该用户此前有有效 job，需一并移除 scheduler 中残留的幽灵 job；
                # 仅当 job 仍存在于 scheduler 时才调用 remove_job（防御性 guard）。
                logger.warning(f"跳过用户 {job_id} 的无效刷新间隔: {e}")
                if job_id in self._jobs:
                    if any(j.id == job_id for j in self._scheduler.get_jobs()):
                        self._scheduler.remove_job(job_id)
                    self._jobs.pop(job_id, None)
                continue
