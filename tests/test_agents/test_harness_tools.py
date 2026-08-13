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


# ── Task 5: LLM 定性工具 + build_investment_tools ──

class FakeLLM:
    def __init__(self, payload): self.payload = payload
    async def json_chat(self, messages): return self.payload


def _ctx_with_llm(state: dict, payload: dict) -> ToolExecutionContext:
    return ToolExecutionContext(cwd=Path("."), metadata={"analysis_state": state, "llm_provider": FakeLLM(payload)})


@pytest.mark.asyncio
async def test_analyze_qualitative():
    from backend.agents.harness_tools import AnalyzeQualitativeTool
    tool = AnalyzeQualitativeTool()
    ctx = _ctx_with_llm({"stock_name": "贵州茅台", "stock_code": "600519", "industry_category": "白酒", "current_price": 50.0},
                        {"moat_assessment": "品牌护城河极深", "risk_factors": ["消费降级"]})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["moat_assessment"] == "品牌护城河极深"
    assert res.metadata["state_updates"]["risk_factors"] == ["消费降级"]


@pytest.mark.asyncio
async def test_anchor_industry_pe_uses_anchor_as_fallback():
    from backend.agents.harness_tools import AnchorIndustryPeTool
    tool = AnchorIndustryPeTool()
    ctx = _ctx_with_llm({"stock_name": "X", "stock_code": "0001", "industry_category": "白酒", "current_price": 50.0},
                        {"pe_low": 18, "pe_high": 22, "pe_rationale": "白酒增速放缓"})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["pe_low"] == 18


@pytest.mark.asyncio
async def test_output_conclusion_guards_rating():
    from backend.agents.harness_tools import OutputConclusionTool
    tool = OutputConclusionTool()
    ctx = _ctx_with_llm({"annual_profit_low": -2.0, "distance_pct": 999.0, "signal_label": "无法量化",
                         "swing_price_low": 0, "swing_price_high": 0, "moat_assessment": "m", "risk_factors": [],
                         "checklist_summary": "s", "checklist_veto": False},
                        {"conclusion": "壁垒深，等待盈利验证", "recommendation": "等待时机-观察区",
                         "unassessable_risk": False, "final_rating": "🟡", "action_items": ["关注订单"]})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["final_rating"] == "🟡"


@pytest.mark.asyncio
async def test_output_conclusion_veto_forces_red():
    from backend.agents.harness_tools import OutputConclusionTool
    from backend.agents.openharness import apply_veto
    tool = OutputConclusionTool()
    ctx = _ctx_with_llm({"annual_profit_low": 10.0, "distance_pct": -5.0, "signal_label": "击球区",
                         "swing_price_low": 1, "swing_price_high": 2, "moat_assessment": "m", "risk_factors": [],
                         "checklist_summary": "重大担忧", "checklist_veto": True},
                        {"conclusion": "c", "recommendation": "可配置", "unassessable_risk": False,
                         "final_rating": "🟢", "action_items": []})
    res = await tool.execute(tool.input_model(), ctx)
    assert res.metadata["state_updates"]["final_rating"] == "🔴"


# ── 恢复 Task 8 丢失的工具测试 ──


@pytest.mark.asyncio
async def test_run_reverse_checklist_maps_to_state(monkeypatch):
    """RunReverseChecklistTool 将 run_reverse_checklist 输出映射到 checklist_* 字段"""
    from backend.agents.harness_tools import RunReverseChecklistTool

    async def fake_run(llm, stock_info):
        return {
            "checklist_results": {"Q1": "有风险", "Q2": "没问题"},
            "checklist_veto": True,
            "most_concerning": "核心护城河五年内可能被削弱",
            "overall_assessment": "证伪充分，存在重大担忧，应暂停买入",
        }

    monkeypatch.setattr("backend.agents.analysis_chain.run_reverse_checklist", fake_run)

    tool = RunReverseChecklistTool()
    ctx = _ctx_with_llm(
        {"stock_name": "贵州茅台", "stock_code": "600519", "current_price": 50.0,
         "pe_dynamic": 22.0, "net_profit_deducted": 34.0, "industry_category": "白酒"},
        {},
    )
    res = await tool.execute(tool.input_model(), ctx)
    updates = res.metadata["state_updates"]

    assert updates["checklist_results"]["Q1"] == "有风险"
    assert updates["checklist_veto"] is True
    assert updates["checklist_summary"] == "证伪充分，存在重大担忧，应暂停买入"
    assert "证伪" in res.output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "industry, payload, expected_low, expected_high",
    [
        # 有锚点行业（白酒 20-35）：非法区间 → 回退锚点
        ("白酒", {"pe_low": 0, "pe_high": 35, "pe_rationale": "无效"}, 20.0, 35.0),
        ("白酒", {"pe_low": 30, "pe_high": 25, "pe_rationale": "倒挂"}, 20.0, 35.0),
        ("白酒", {"pe_low": "n/a", "pe_high": "n/a", "pe_rationale": "非数值"}, 20.0, 35.0),
        # 无锚点行业 → 默认 15-25
        ("未知行业", {"pe_low": -5, "pe_high": 10, "pe_rationale": "无效"}, 15.0, 25.0),
        ("", {"pe_low": 30, "pe_high": 20, "pe_rationale": "倒挂"}, 15.0, 25.0),
        ("未知行业", {"pe_low": "n/a", "pe_high": "n/a", "pe_rationale": "非数值"}, 15.0, 25.0),
    ],
)
async def test_anchor_industry_pe_invalid_ranges_fall_back(
    industry, payload, expected_low, expected_high
):
    """AnchorIndustryPeTool 对非法区间回退锚点/默认 15-25"""
    from backend.agents.harness_tools import AnchorIndustryPeTool
    tool = AnchorIndustryPeTool()
    ctx = _ctx_with_llm(
        {"stock_name": "X", "stock_code": "0001", "industry_category": industry, "current_price": 50.0},
        payload,
    )
    res = await tool.execute(tool.input_model(), ctx)
    updates = res.metadata["state_updates"]
    assert updates["pe_low"] == expected_low
    assert updates["pe_high"] == expected_high


@pytest.mark.asyncio
async def test_output_conclusion_writes_confidence_and_action_items():
    """OutputConclusionTool 写入 rating_confidence/action_items，透传 recommendation"""
    from backend.agents.harness_tools import OutputConclusionTool
    tool = OutputConclusionTool()
    ctx = _ctx_with_llm(
        {"annual_profit_low": 32.0, "distance_pct": 15.0, "signal_label": "观察区",
         "swing_price_low": 10, "swing_price_high": 20, "moat_assessment": "m", "risk_factors": [],
         "checklist_summary": "s", "checklist_veto": False},
        {"final_rating": "🟡", "recommendation": "距击球区 15%，观察区，等待更好时机",
         "action_items": ["设定击球点提醒", "持续跟踪基本面"]},
    )
    res = await tool.execute(tool.input_model(), ctx)
    updates = res.metadata["state_updates"]

    assert updates["final_rating"] == "🟡"
    assert "观察" in updates["recommendation"]
    assert updates["rating_confidence"] == 0.75
    assert updates["action_items"] == ["设定击球点提醒", "持续跟踪基本面"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, expected", [
    ({"final_rating": "INVALID", "recommendation": "x", "action_items": []}, "🟡"),
    ({"final_rating": None, "recommendation": "x", "action_items": []}, "🟡"),
    ({"final_rating": "🔴", "recommendation": "x", "action_items": []}, "🔴"),
])
async def test_output_conclusion_rating_guard(payload, expected):
    """final_rating 非法 → 默认 🟡；合法值原样保留"""
    from backend.agents.harness_tools import OutputConclusionTool
    tool = OutputConclusionTool()
    ctx = _ctx_with_llm(
        {"annual_profit_low": 32.0, "distance_pct": 15.0, "signal_label": "观察区",
         "swing_price_low": 10, "swing_price_high": 20, "moat_assessment": "m", "risk_factors": [],
         "checklist_summary": "s", "checklist_veto": False},
        payload,
    )
    res = await tool.execute(tool.input_model(), ctx)
    updates = res.metadata["state_updates"]
    assert updates["final_rating"] == expected


@pytest.mark.asyncio
async def test_build_investment_tools_registers_9():
    from backend.agents.harness_tools import build_investment_tools
    tools = build_investment_tools(None)
    names = [t.name for t in tools]
    assert len(names) == 9
    assert "calc_swing_zone" in names and "output_conclusion" in names
