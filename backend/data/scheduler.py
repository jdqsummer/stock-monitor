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

    def add_analysis_job(self, func, morning_time: str = "09:30", afternoon_time: str = "15:30"):
        """添加分析更新任务（早盘/收盘）"""
        hour_m, minute_m = morning_time.split(":")
        hour_a, minute_a = afternoon_time.split(":")

        # 早盘分析
        job_m = self._scheduler.add_job(
            func,
            CronTrigger(hour=int(hour_m), minute=int(minute_m), day_of_week="mon-fri"),
            id="analysis_morning",
            name="早盘分析",
            replace_existing=True,
        )
        self._jobs["analysis_morning"] = job_m

        # 收盘分析
        job_a = self._scheduler.add_job(
            func,
            CronTrigger(hour=int(hour_a), minute=int(minute_a), day_of_week="mon-fri"),
            id="analysis_afternoon",
            name="收盘分析",
            replace_existing=True,
        )
        self._jobs["analysis_afternoon"] = job_a

        logger.info(f"分析任务已注册: 早{morning_time} 下午{afternoon_time}")

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
