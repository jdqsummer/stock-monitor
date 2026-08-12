"""OpenHarnessAgent 测试"""
import pytest

from backend.agents.analysis_chain import run_reverse_checklist
from backend.agents.openharness import OpenHarnessAgent


class FakeChecklistLLM:
    async def json_chat(self, messages):
        return {
            "checklist_results": {"Q1": "有风险", "Q2": "没问题"},
            "checklist_veto": True,
            "most_concerning": "核心护城河五年内可能被削弱",
            "overall_assessment": "证伪充分，存在重大担忧，应暂停买入",
        }


def make_state(**overrides) -> dict:
    base = {
        "stock_code": "600519",
        "stock_name": "测试股",
        "current_price": 50.0,
        "total_market_cap": 750.0,
        "total_shares": 15.0,
        "pe_dynamic": 22.0,
        "net_profit_parent": 35.0,
        "net_profit_deducted": 34.0,
        "industry_category": "白酒",
        "financials": [],
        "news": [],
        "errors": [],
        "warnings": [],
        "checklist_results": {},
        "checklist_veto": False,
        "checklist_summary": "",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_analyze_without_llm_runs_rule_based():
    """无 LLM → 纯规则子链，产出完整分析字段"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    result = await agent.analyze(state)

    assert result["annual_profit_low"] > 0
    assert result["pe_low"] == 20.0          # 白酒锚定
    assert result["swing_price_low"] > 0
    assert result["signal"] in ("green", "yellow", "red")
    assert result["final_rating"]
    assert result["recommendation"]


@pytest.mark.asyncio
async def test_tool_calc_swing_zone_is_deterministic():
    """击球区计算工具返回确定性数值"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
    )
    updates, text = await agent._tool_calc_swing_zone(state, {})

    assert updates["swing_market_cap_low"] == 576.0
    assert updates["swing_market_cap_high"] == 770.0
    assert updates["swing_price_low"] == 38.4
    assert "击球区" in text


@pytest.mark.asyncio
async def test_execute_tool_dispatches_by_name():
    """_execute_tool 按名称分发到工具"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(
        annual_profit_low=32.0, annual_profit_high=35.0,
        pe_low=18.0, pe_high=22.0, total_shares=15.0,
    )
    updates, _ = await agent._execute_tool("calc_swing_zone", {}, state)
    assert updates["swing_price_low"] == 38.4


@pytest.mark.asyncio
async def test_tool_run_reverse_checklist(monkeypatch):
    """清单工具返回结构化证伪结果并写入 state"""
    import backend.agents.openharness as oh
    monkeypatch.setattr(oh, "run_reverse_checklist", lambda llm, info: FakeChecklistLLM().json_chat(None))

    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state(stock_name="贵州茅台")
    updates, text = await agent._tool_run_reverse_checklist(state, {})

    assert updates["checklist_results"]["Q1"] == "有风险"
    assert updates["checklist_veto"] is True
    assert updates["checklist_summary"] == "证伪充分，存在重大担忧，应暂停买入"
    assert "证伪" in text
