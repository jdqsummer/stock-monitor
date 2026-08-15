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


@pytest.mark.asyncio
async def test_sync_auto_analysis_jobs_skips_bad_time():
    async def collect():
        return [("u1", "bad"), ("u2", "15:30"), ("u3", "25:00")]

    sched = TaskScheduler()
    sched.start()
    try:
        await sched.sync_auto_analysis_jobs(
            collect_func=collect,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u2" in ids
        assert "auto_u1" not in ids
        assert "auto_u3" not in ids
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_sync_auto_analysis_jobs_removes_phantom_on_bad_time_mutation():
    """有效时间 → 非法时间变更：残留 scheduler job（幽灵 job）必须被清理。"""
    async def collect_valid():
        return [("u1", "15:30")]

    async def collect_bad():
        return [("u1", "bad")]

    sched = TaskScheduler()
    sched.start()
    try:
        # 先注册有效 job
        await sched.sync_auto_analysis_jobs(
            collect_func=collect_valid,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" in ids

        # 用户改为非法时间 → 不抛异常，且旧 job 不再残留于 scheduler
        await sched.sync_auto_analysis_jobs(
            collect_func=collect_bad,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" not in ids
        assert "auto_u1" not in sched._jobs

        # 再次 reconcile 仍稳定（无幽灵 job 干扰）
        await sched.sync_auto_analysis_jobs(
            collect_func=collect_bad,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" not in ids
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_sync_auto_analysis_jobs_removes_phantom_on_out_of_range_mutation():
    """有效时间 → 越界时间（"25:00"，split 成功但 CronTrigger 校验失败）变更：同样无幽灵 job。"""
    async def collect_valid():
        return [("u1", "15:30")]

    async def collect_oob():
        return [("u1", "25:00")]

    sched = TaskScheduler()
    sched.start()
    try:
        await sched.sync_auto_analysis_jobs(
            collect_func=collect_valid,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" in ids

        # 越界时间：try 内 remove_job 已执行过，except 不应重复调用 remove_job
        await sched.sync_auto_analysis_jobs(
            collect_func=collect_oob,
            run_func=lambda user_id: None,
        )
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "auto_u1" not in ids
        assert "auto_u1" not in sched._jobs
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_sync_quote_refresh_jobs_registers_and_removes():
    async def collect1():
        return [("u1", 30), ("u2", 15)]
    async def collect2():
        return [("u1", 30)]

    sched = TaskScheduler()
    sched.start()
    try:
        await sched.sync_quote_refresh_jobs(collect_func=collect1, run_func=lambda u: None)
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "quote_u1" in ids and "quote_u2" in ids
        await sched.sync_quote_refresh_jobs(collect_func=collect2, run_func=lambda u: None)
        ids = {j.id for j in sched._scheduler.get_jobs()}
        assert "quote_u1" in ids and "quote_u2" not in ids
    finally:
        sched.shutdown()
