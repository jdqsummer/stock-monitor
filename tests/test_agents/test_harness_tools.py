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
    CalcSafetyMarginTool,
    CalcSwingZoneTool,
    EstimateAnnualProfitTool,
    ReadContextTool,
)
from backend.schemas.stock import FinancialReport  # noqa: E402


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
    assert updates["distance_pct"] == -2.0
    assert updates["signal"] == "green"


@pytest.mark.asyncio
async def test_calc_safety_margin_loss_returns_unquantifiable():
    tool = CalcSafetyMarginTool()
    res = await tool.execute(
        tool.input_model(current_price=50.0, swing_price_high=51.0, annual_profit_low=-2.0),
        _ctx({}),
    )
    assert res.metadata["state_updates"]["signal"] == "unquantifiable"


@pytest.mark.asyncio
async def test_estimate_annual_profit_writes_method():
    tool = EstimateAnnualProfitTool()
    state = {"net_profit_deducted": 34.0, "financials": []}
    res = await tool.execute(tool.input_model(), _ctx(state))
    assert res.metadata["state_updates"]["annual_profit_low"] > 0
    assert "profit_method" in res.metadata["state_updates"]


@pytest.mark.asyncio
async def test_read_context_shows_multiperiod_financials():
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
        "financials": [
            FinancialReport(code="600519", name="贵州茅台", report_period="2026H1",
                            revenue=120.0, net_profit_parent=35.0, net_profit_deducted=32.0),
            FinancialReport(code="600519", name="贵州茅台", report_period="2025FY",
                            revenue=230.0, net_profit_parent=66.0, net_profit_deducted=62.0),
        ],
        "news": ["a", "b"],
    }
    res = await tool.execute(tool.input_model(), _ctx(state))
    assert "贵州茅台" in res.output and "600519" in res.output
    assert "财报期数: 2" in res.output
    assert "新闻条数: 2" in res.output
    assert "2026H1" in res.output and "2025FY" in res.output
    assert "120.0" in res.output and "62.0" in res.output


@pytest.mark.asyncio
async def test_build_investment_tools_registers_expected():
    from backend.agents.harness_tools import build_investment_tools
    tools = build_investment_tools(None)
    names = [t.name for t in tools]
    expected = {"read_context", "analyze_qualitative", "run_reverse_checklist",
                "anchor_industry_pe", "output_conclusion",
                "estimate_annual_profit", "calc_swing_zone", "calc_safety_margin"}
    # 精确相等：旧 9 工具含 assess_profit_quality，新 8 工具不含；
    # skill 工具由 harness_component.run_analysis_agent 单独注册（需 extra_skill_dirs）。
    assert set(names) == expected
    assert "validate_constraints" not in names
    assert "assess_profit_quality" not in names
