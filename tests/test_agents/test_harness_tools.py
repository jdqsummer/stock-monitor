"""harness 投资工具测试（确定性工具）"""
import sys
from pathlib import Path

import pytest

# 确保 vendor/ 在 sys.path 上，使 vendored openharness 可导入
# （mirror Task 1 的 tests/test_vendor/test_openharness_vendor.py 模式）
_VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


_ensure_vendor_on_path()

from openharness.tools.base import ToolExecutionContext  # noqa: E402

from backend.agents.harness_tools import (  # noqa: E402
    AssessProfitQualityTool,
    CalcSafetyMarginTool,
    CalcSwingZoneTool,
    EstimateAnnualProfitTool,
    ReadContextTool,
)


def _ctx(state: dict) -> ToolExecutionContext:
    return ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state})


@pytest.mark.asyncio
async def test_calc_swing_zone_deterministic():
    tool = CalcSwingZoneTool()
    res = await tool.execute(
        tool.input_model(annual_profit_low=32.0, annual_profit_high=35.0,
                         pe_low=18.0, pe_high=22.0, total_shares=15.0),
        _ctx({}),
    )
    assert res.metadata["state_updates"]["swing_market_cap_low"] == 576.0
    assert res.metadata["state_updates"]["swing_market_cap_high"] == 770.0
    assert res.metadata["state_updates"]["swing_price_low"] == 38.4
    assert "击球区" in res.output


@pytest.mark.asyncio
async def test_calc_safety_margin_deterministic():
    tool = CalcSafetyMarginTool()
    res = await tool.execute(
        tool.input_model(current_price=50.0, swing_price_high=51.0, annual_profit_low=32.0),
        _ctx({}),
    )
    updates = res.metadata["state_updates"]
    assert updates["distance_pct"] == -1.96
    assert updates["signal"] == "green"


@pytest.mark.asyncio
async def test_calc_safety_margin_loss_returns_unquantifiable():
    tool = CalcSafetyMarginTool()
    res = await tool.execute(
        tool.input_model(current_price=50.0, swing_price_high=51.0, annual_profit_low=-2.0),
        _ctx({}),
    )
    assert res.metadata["state_updates"]["signal"] == "red"


@pytest.mark.asyncio
async def test_estimate_annual_profit_writes_method():
    tool = EstimateAnnualProfitTool()
    state = {"net_profit_deducted": 34.0, "financials": []}
    res = await tool.execute(tool.input_model(), _ctx(state))
    assert res.metadata["state_updates"]["annual_profit_low"] > 0
    assert "profit_method" in res.metadata["state_updates"]


@pytest.mark.asyncio
async def test_read_context_concise_summary():
    tool = ReadContextTool()
    state = {
        "stock_name": "贵州茅台",
        "stock_code": "600519",
        "current_price": 1400.0,
        "total_market_cap": 17590.0,
        "total_shares": 12.56,
        "pe_dynamic": 25.0,
        "net_profit_parent": 747.0,
        "net_profit_deducted": 745.0,
        "industry_category": "白酒",
        "financials": [1, 2, 3],
        "news": ["a", "b"],
    }
    res = await tool.execute(tool.input_model(), _ctx(state))
    assert "贵州茅台" in res.output
    assert "600519" in res.output
    assert "财报期数: 3" in res.output
    assert "新闻条数: 2" in res.output


@pytest.mark.asyncio
async def test_assess_profit_quality_flags_non_recurring():
    tool = AssessProfitQualityTool()
    state = {"financials": [], "net_profit_parent": 100.0, "net_profit_deducted": 70.0}
    res = await tool.execute(tool.input_model(), _ctx(state))
    updates = res.metadata["state_updates"]
    assert updates["profit_quality_ok"] is False  # 非经常性占比 30% > 20% 阈值
    assert any("非经常性" in w for w in updates["profit_quality_warnings"])
    assert "存疑" in res.output


@pytest.mark.asyncio
async def test_assess_profit_quality_ok_when_clean():
    tool = AssessProfitQualityTool()
    state = {"financials": [], "net_profit_parent": 90.0, "net_profit_deducted": 88.0}
    res = await tool.execute(tool.input_model(), _ctx(state))
    updates = res.metadata["state_updates"]
    assert updates["profit_quality_ok"] is True
    assert "良好" in res.output
