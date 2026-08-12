import pytest

from backend.data.scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_sync_auto_analysis_jobs_registers_per_user():
    async def collect1():
        return [("u1", "15:30"), ("u2", "16:00")]

    async def collect2():
        return [("u1", "15:30")]

    sched = TaskScheduler()
    sched.start()
    try:
        await sched.sync_auto_analysis_jobs(
            collect_func=collect1,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" in ids
        assert "auto_u2" in ids
        # 变化后 reconcile：u2 关闭 → 只留 u1
        await sched.sync_auto_analysis_jobs(
            collect_func=collect2,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" in ids
        assert "auto_u2" not in ids
    finally:
        sched.shutdown()
