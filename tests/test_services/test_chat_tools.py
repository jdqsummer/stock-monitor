"""聊天工具执行器 — TDD"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.stock import AnalysisSnapshot, FinancialRecord, StockSnapshot
from backend.schemas.stock import FinancialReport
from backend.services.chat_tools import (
    TOOL_SCHEMAS, execute_tool, get_financials_tool, get_industry_pe_tool,
    run_five_stage_tool,
)


def test_tool_schemas_has_five_tools():
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert names == ["get_stock_snapshot", "get_financials", "search_stock",
                     "get_industry_pe", "run_five_stage"]


@pytest.mark.asyncio
async def test_get_stock_snapshot_tool_reads_snapshot():
    """行情工具读 A 表 + B 表返回紧凑 dict"""
    db = MagicMock()
    # A 表行情（total_market_cap 单位：亿元；update_time 为 datetime 列，工具须转 ISO 字符串）
    quote = StockSnapshot(code="600519", name="贵州茅台", current_price=1500.0,
                          change_pct=1.2, total_market_cap=19500.0, pe_dynamic=28.0,
                          total_shares=12.56, update_time=datetime(2026, 8, 22, 15, 0))
    # B 表快照
    snap = AnalysisSnapshot(user_id="u1", stock_code="600519", signal="yellow",
                            distance_pct=15.2, swing_price_low=1200.0, swing_price_high=1400.0,
                            sell_signal="none", annual_profit_low=700.0, annual_profit_high=750.0)
    with patch("backend.services.chat_tools.StockDataService.get_quote_for_code",
               AsyncMock(return_value=quote)), \
         patch("backend.services.chat_tools._load_snapshot", AsyncMock(return_value=snap)):
        out = await execute_tool(db, "u1", "get_stock_snapshot", {"code": "600519"})

    assert out["code"] == "600519"
    assert out["name"] == "贵州茅台"
    assert out["signal"] == "yellow"
    assert out["distance_pct"] == 15.2
    assert out["total_market_cap"] == 19500.0
    assert out["total_shares"] == 12.56
    assert out["change_pct"] == 1.2
    assert "2026-08-22" in out["update_time"]  # datetime → ISO 字符串，保证 json.dumps 可序列化


@pytest.mark.asyncio
async def test_run_five_stage_submits_job():
    """run_five_stage 提交 analysis job 返回 job_id，不阻塞"""
    db = MagicMock()
    job_svc = MagicMock(submit=MagicMock(return_value="job_chat_1"))
    with patch("backend.services.chat_tools.analysis_job_service", job_svc):
        out = await run_five_stage_tool(db, {"code": "600519", "_user_id": "u1"})
    assert out["job_id"] == "job_chat_1"
    job_svc.submit.assert_called_once()


@pytest.mark.asyncio
async def test_get_financials_reads_snapshot_table():
    """静态快照表有数据 → 直接映射返回（snapshot 源）"""
    db = MagicMock()
    record = FinancialRecord(code="600519", report_period="2026H1", revenue=922.78,
                             net_profit_parent=445.17, net_profit_deducted=430.0,
                             updated_at=datetime.now())  # 修复 1：陈旧检测需要非 None 的 updated_at
    snap_result = MagicMock()
    snap_result.scalars.return_value.all.return_value = [record]
    # 修复 1：第二个 query 查 max(updated_at)；返回当前时间 → < 1h → 不陈旧 → source=snapshot
    max_result = MagicMock()
    max_result.scalar.return_value = datetime.now()
    db.execute = AsyncMock(side_effect=[snap_result, max_result])

    out = await get_financials_tool(db, {"code": "600519"})

    assert out["code"] == "600519"
    assert out["source"] == "snapshot"
    assert out["financials"][0]["period"] == "2026H1"
    assert out["financials"][0]["revenue"] == 922.78
    assert out["financials"][0]["net_profit_parent"] == 445.17


@pytest.mark.asyncio
async def test_get_financials_live_fallback_when_table_empty():
    """静态快照表无数据 → 实时兜底（live 源）"""
    db = MagicMock()
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    # 修复 1：A 表空 → 跳过陈旧检测 → 直接走"完全无数据兜底"
    db.execute = AsyncMock(return_value=empty_result)
    report = FinancialReport(code="600519", name="贵州茅台", report_period="2026H1",
                             revenue=922.78, net_profit_parent=445.17,
                             net_profit_deducted=430.0)

    with patch("backend.services.chat_tools._client.fetch_financials",
               AsyncMock(return_value=[report])):
        out = await get_financials_tool(db, {"code": "600519"})

    assert out["source"] == "live"
    assert out["financials"][0]["period"] == "2026H1"
    assert out["financials"][0]["revenue"] == 922.78


@pytest.mark.asyncio
async def test_get_financials_live_fallback_error_returns_empty():
    """静态表空 + 实时兜底异常 → 空列表不崩溃（live-fallback-none 源）"""
    db = MagicMock()
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=empty_result)

    with patch("backend.services.chat_tools._client.fetch_financials",
               AsyncMock(side_effect=Exception("数据源不可用"))):
        out = await get_financials_tool(db, {"code": "600519"})

    assert out["financials"] == []
    assert out["source"] == "live-fallback-none"


@pytest.mark.asyncio
async def test_execute_tool_unknown_raises():
    db = MagicMock()
    with pytest.raises(ValueError):
        await execute_tool(db, "u1", "no_such_tool", {})


# ── 修复 1：chat 财报陈旧检测 + Redis 限流实时兜底 ──

@pytest.mark.asyncio
async def test_get_financials_stale_triggers_live_refresh():
    """A 表 > 1h 陈旧 + 获取到锁 → 实时拉取并覆盖（live-refreshed 源）"""
    from datetime import timedelta
    from backend.services.chat_tools import _financial_lock_cache

    db = MagicMock()
    record = FinancialRecord(
        code="600519", report_period="2026H1", revenue=922.78,
        net_profit_parent=445.17, net_profit_deducted=430.0,
        updated_at=datetime.now() - timedelta(hours=2),  # 2h 前 → 陈旧
    )
    fresh_record = FinancialRecord(
        code="600519", report_period="2026H1", revenue=950.0,
        net_profit_parent=460.0, net_profit_deducted=445.0,
        updated_at=datetime.now(),
    )
    # _read_snapshot 第一次 + 第二次（实时拉完再读）
    snap_old = MagicMock()
    snap_old.scalars.return_value.all.return_value = [record]
    max_old = MagicMock()
    max_old.scalar.return_value = record.updated_at  # 2h 前
    # 实时拉取后 _upsert_financial 内部查 + 新 _read_snapshot
    upsert_lookup = MagicMock()
    upsert_lookup.scalar_one_or_none.return_value = record  # 已存在，update 分支
    snap_new = MagicMock()
    snap_new.scalars.return_value.all.return_value = [fresh_record]
    db.execute = AsyncMock(side_effect=[snap_old, max_old, upsert_lookup, snap_new])
    db.commit = AsyncMock()

    report = FinancialReport(code="600519", name="贵州茅台", report_period="2026H1",
                             revenue=950.0, net_profit_parent=460.0,
                             net_profit_deducted=445.0, is_official=True)

    with patch.object(_financial_lock_cache, "try_acquire_lock", AsyncMock(return_value=True)), \
         patch("backend.services.chat_tools._client.fetch_financials",
               AsyncMock(return_value=[report])):
        out = await get_financials_tool(db, {"code": "600519"})

    assert out["source"] == "live-refreshed"
    assert out["financials"][0]["revenue"] == 950.0  # 新数据


@pytest.mark.asyncio
async def test_get_financials_stale_locked_skips_refresh():
    """A 表陈旧但锁被持有 → 跳过实时拉取，用 A 表（snapshot-locked 源）"""
    from datetime import timedelta
    from backend.services.chat_tools import _financial_lock_cache

    db = MagicMock()
    record = FinancialRecord(
        code="600519", report_period="2026H1", revenue=922.78,
        net_profit_parent=445.17, net_profit_deducted=430.0,
        updated_at=datetime.now() - timedelta(hours=2),
    )
    snap = MagicMock()
    snap.scalars.return_value.all.return_value = [record]
    max_q = MagicMock()
    max_q.scalar.return_value = record.updated_at
    db.execute = AsyncMock(side_effect=[snap, max_q])

    with patch.object(_financial_lock_cache, "try_acquire_lock", AsyncMock(return_value=False)), \
         patch("backend.services.chat_tools._client.fetch_financials") as mock_fetch:
        out = await get_financials_tool(db, {"code": "600519"})

    assert out["source"] == "snapshot-locked"
    mock_fetch.assert_not_called()  # 锁住 → 不调 Provider


@pytest.mark.asyncio
async def test_get_financials_stale_live_failure_keeps_snapshot():
    """实时拉取失败（异常）→ 保留 A 表旧数据（snapshot 源，不让聊天失败）"""
    from datetime import timedelta
    from backend.services.chat_tools import _financial_lock_cache

    db = MagicMock()
    record = FinancialRecord(
        code="600519", report_period="2026H1", revenue=922.78,
        net_profit_parent=445.17, net_profit_deducted=430.0,
        updated_at=datetime.now() - timedelta(hours=2),
    )
    snap = MagicMock()
    snap.scalars.return_value.all.return_value = [record]
    max_q = MagicMock()
    max_q.scalar.return_value = record.updated_at
    db.execute = AsyncMock(side_effect=[snap, max_q])

    with patch.object(_financial_lock_cache, "try_acquire_lock", AsyncMock(return_value=True)), \
         patch("backend.services.chat_tools._client.fetch_financials",
               AsyncMock(side_effect=Exception("东财 503"))):
        out = await get_financials_tool(db, {"code": "600519"})

    assert out["source"] == "snapshot"  # 回退
    assert out["financials"][0]["revenue"] == 922.78
