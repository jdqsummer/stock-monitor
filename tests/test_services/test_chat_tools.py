"""聊天工具执行器 — TDD"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.stock import AnalysisSnapshot, FinancialRecord, StockSnapshot
from backend.services.chat_tools import (
    TOOL_SCHEMAS, execute_tool, get_industry_pe_tool, run_five_stage_tool,
)


def test_tool_schemas_has_five_tools():
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert names == ["get_stock_snapshot", "get_financials", "search_stock",
                     "get_industry_pe", "run_five_stage"]


@pytest.mark.asyncio
async def test_get_stock_snapshot_tool_reads_snapshot():
    """行情工具读 A 表 + B 表返回紧凑 dict"""
    db = MagicMock()
    # A 表行情
    quote = StockSnapshot(code="600519", name="贵州茅台", current_price=1500.0,
                          change_pct=1.2, total_market_cap=1.8e12, pe_dynamic=28.0,
                          total_shares=12.56)
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
async def test_execute_tool_unknown_raises():
    db = MagicMock()
    with pytest.raises(ValueError):
        await execute_tool(db, "u1", "no_such_tool", {})
