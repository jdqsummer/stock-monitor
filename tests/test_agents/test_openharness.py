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


# ── LLM 模式派发 DSH（P3 Task 4）──


@pytest.mark.asyncio
async def test_analyze_with_real_llm_delegates_to_dsh(monkeypatch):
    """有真实 LLM + DSH 可用 → 委托 DshOrchestrator.analyze"""
    from backend.agents import openharness as oh
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    sentinel = {"final_rating": "🔴", "analysis_source": "dsh-llm",
                "analysis_model": "deepseek-v4-flash", "analysis_degraded": False}

    async def _fake_analyze(self, state, model=""):
        return sentinel

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _fake_analyze)

    agent = oh.OpenHarnessAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result is sentinel


@pytest.mark.asyncio
async def test_analyze_dsh_unavailable_falls_back_to_rule_based(monkeypatch):
    """DSH 未配置（is_available=False）→ 降级规则子链 + 降级标记"""
    from backend.agents import openharness as oh
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: False)

    agent = oh.OpenHarnessAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result["analysis_source"] == "rule-based"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True
    assert result["final_rating"] in ("🟢", "🟡", "🔴")


@pytest.mark.asyncio
async def test_analyze_dsh_failure_falls_back_to_rule_based(monkeypatch):
    """DSH 可用但抛错 → 降级规则子链 + 降级标记 + errors 记录"""
    from backend.agents import openharness as oh
    from backend.agents.dsh_orchestrator import DshOrchestrator
    from backend.llm.provider import LLMConfig, ProviderType

    async def _boom(self, state, model=""):
        raise RuntimeError("dsh boom")

    monkeypatch.setattr(DshOrchestrator, "is_available", lambda: True)
    monkeypatch.setattr(DshOrchestrator, "analyze", _boom)

    agent = oh.OpenHarnessAgent(llm_provider=SimpleNamespace())
    agent.llm.config = LLMConfig(provider=ProviderType.DEEPSEEK, model_id="x")
    result = await agent.analyze(make_state())
    assert result["final_rating"] in ("🟢", "🟡", "🔴")
    assert result["analysis_source"] == "rule-based"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True
    assert any("DSH 分析降级" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_rule_based_when_no_llm_marks_degraded():
    """无 LLM → 纯规则降级 + 引擎标记（analysis_source 全路径）"""
    agent = OpenHarnessAgent(llm_provider=None)
    state = make_state()
    updates = await agent.analyze(state)
    assert updates.get("analysis_source") in {"rule-based", "mock"}
    assert updates.get("analysis_degraded") is True
    assert updates.get("analysis_model") == "none"


@pytest.mark.asyncio
async def test_analyze_mock_llm_marks_mock():
    """Mock LLM → has_real_llm=False 且 _is_mock=True → analysis_source=mock"""
    from backend.llm.provider import LLMConfig, MockLLMProvider, ProviderType

    agent = OpenHarnessAgent(
        llm_provider=MockLLMProvider(LLMConfig(provider=ProviderType.MOCK, model_id="mock"))
    )
    result = await agent.analyze(make_state())
    assert result["analysis_source"] == "mock"
    assert result["analysis_model"] == "none"
    assert result["analysis_degraded"] is True


def test_build_investment_tools_excludes_validate_constraints():
    """validate_constraints 工具已移除（硬约束软化）；至少 8 工具 = 只读 + 4 阶段 + 3 定量"""
    from backend.agents.harness_tools import build_investment_tools

    names = [t.name for t in build_investment_tools(None)]
    assert "validate_constraints" not in names
    assert len(names) >= 8


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
