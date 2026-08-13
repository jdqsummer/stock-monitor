"""OpenHarnessAgent 测试"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 确保 vendor/ 在 sys.path 上，使 vendored openharness 可导入
# （LLM 模式委托 harness_component，其依赖 vendored openharness）
_VENDOR = Path(__file__).resolve().parents[2] / "vendor"


def _ensure_vendor_on_path():
    if str(_VENDOR) not in sys.path:
        sys.path.insert(0, str(_VENDOR))


_ensure_vendor_on_path()

from backend.agents.openharness import OpenHarnessAgent, apply_veto  # noqa: E402


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


# ── Task 8: LLM 模式走 harness 组件 ──


@pytest.mark.asyncio
async def test_analyze_with_llm_delegates_to_component(monkeypatch):
    """有真实 LLM → 委托 harness_component.run_analysis_agent"""
    from backend.agents import openharness as oh
    from backend.llm.provider import LLMConfig, ProviderType

    sentinel = {"final_rating": "🔴"}

    async def _fake(state, **kw):
        return sentinel

    monkeypatch.setattr("backend.agents.harness_component.run_analysis_agent", _fake)

    agent = oh.OpenHarnessAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result is sentinel


@pytest.mark.asyncio
async def test_analyze_component_failure_falls_back(monkeypatch):
    """组件抛错 → 降级规则子链，errors 记录"""
    from backend.agents import openharness as oh
    from backend.llm.provider import LLMConfig, ProviderType

    async def _boom(state, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("backend.agents.harness_component.run_analysis_agent", _boom)

    agent = oh.OpenHarnessAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state(annual_profit_low=32.0, annual_profit_high=35.0,
                                            pe_low=20.0, pe_high=35.0, distance_pct=10.0))
    assert result["final_rating"] in ("🟢", "🟡", "🔴")
    assert any("降级" in e for e in result["errors"])


def test_build_investment_tools_excludes_validate_constraints():
    """validate_constraints 工具已从 9 工具移除（硬约束软化）"""
    from backend.agents.harness_tools import build_investment_tools

    names = [t.name for t in build_investment_tools(None)]
    assert "validate_constraints" not in names
    assert len(names) == 9


# ── 硬约束校验（规则子链兜底用） ──


@pytest.mark.asyncio
async def test_apply_hard_constraints_writes_errors():
    """硬约束失败写入 state.errors"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    from backend.agents.state import ConstraintResult
    results = [
        ConstraintResult(constraint_name="纪律红线", passed=False, severity="error",
                         message="距击球区 > 50%", suggestion="不追高", auto_fixable=False),
    ]
    messages = agent._apply_hard_constraints(state, results)
    assert messages == ["[纪律红线] 距击球区 > 50%"]
    assert state["errors"] == ["[纪律红线] 距击球区 > 50%"]


@pytest.mark.asyncio
async def test_apply_hard_constraints_dedupes_errors():
    """硬约束重复校验时 errors 不重复追加"""
    agent = OpenHarnessAgent(llm_provider=None)
    from backend.agents.state import ConstraintResult
    results = [
        ConstraintResult(constraint_name="纪律红线", passed=False, severity="error",
                         message="亏损企业必评🔴", suggestion="下调评级", auto_fixable=False),
    ]
    state = make_state()
    agent._apply_hard_constraints(state, results)
    agent._apply_hard_constraints(state, results)
    assert state["errors"].count("[纪律红线] 亏损企业必评🔴") == 1


# ── apply_veto ──


def test_apply_veto_unassessable_risk_forces_red():
    """unassessable_risk → 强制 🔴 坚决放弃，且不改 signal"""
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": False, "signal": "green"})
    assert updates["final_rating"] == "🔴"
    assert "坚决放弃" in updates["recommendation"]
    assert "signal" not in updates


def test_apply_veto_checklist_veto_forces_red():
    updates = apply_veto({"unassessable_risk": False, "checklist_veto": True})
    assert updates["final_rating"] == "🔴"
    assert "否决项" in updates["recommendation"]


def test_apply_veto_none_returns_empty():
    assert apply_veto({"unassessable_risk": False, "checklist_veto": False}) == {}


def test_apply_veto_priority_unassessable_over_checklist():
    updates = apply_veto({"unassessable_risk": True, "checklist_veto": True})
    assert "无法评估" in updates["recommendation"]


def test_apply_veto_includes_conclusion():
    """否决覆盖 conclusion（spec §4：veto 覆盖 final_rating/recommendation/conclusion）"""
    u = apply_veto({"unassessable_risk": True, "checklist_veto": False})
    assert u["final_rating"] == "🔴"
    assert u["conclusion"]
    assert "不可买入" in u["conclusion"]


# ── 规则子链降级路径仍确定性执行约束 ──


@pytest.mark.asyncio
async def test_rule_based_path_still_enforces_constraints():
    """规则子链降级路径仍走约束引擎（确定性兜底保留）。

    覆盖两处确定性语义：
    1. 亏损（net_profit_deducted ≤ 0）→ "亏损不年化" → signal=unquantifiable → 🟡
       （亏损不机械判红，软规则语义已由「统一亏损语义」提交确立）
    2. 非经常性水分 > 50% → 硬约束（纪律红线·利润质量）→ 🔴
    """
    agent = OpenHarnessAgent(llm_provider=None)

    # 亏损：确定性 🟡 观察区，安全边际无法量化
    loss = make_state(net_profit_deducted=-2.0, net_profit_parent=-2.0)
    loss_result = await agent._rule_based(loss)
    assert loss_result["profit_method"] == "亏损不年化"
    assert loss_result["signal"] == "unquantifiable"
    assert loss_result["final_rating"] == "🟡"
    assert "无法量化" in loss_result["recommendation"]

    # 非经常性水分 > 50%：确定性 🔴，硬约束仍强制执行并写入 errors
    watery = make_state(net_profit_parent=100.0, net_profit_deducted=20.0)
    watery_result = await agent._rule_based(watery)
    assert watery_result["final_rating"] == "🔴"
    assert any("利润质量" in e for e in watery_result["errors"])
